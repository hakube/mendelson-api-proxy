"""
AS2Session: a single authenticated connection to the Mendelson AS2 server.

Usage:
    with AS2Session(host, port, user, password) as s:
        partners = s.list_partners()
        messages = s.list_messages(limit=100)

The session handles:
  - TLS connect
  - reading the ServerInfo hello
  - sending LoginRequest and reading LoginState
  - sending requests and reading typed responses
  - sending QuitRequest on close
"""

import re
import socket
import ssl
from contextlib import contextmanager

from .javaobj import JavaReader, read_frame, send_frame
from .messages import (
    build_login_request,
    build_quit_request,
    build_partner_list_request,
    build_message_overview_request,
    build_message_log_request,
    build_message_payload_request,
)


class AS2AuthError(Exception):
    pass


class AS2Session:
    LOGIN_SUCCESS = 1
    LOGIN_FAILURE = 2

    def __init__(self, host: str, port: int, user: str, password: str, timeout: float = 30.0):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.timeout = timeout
        self._sock = None
        self.server_version: str = ""

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock = ctx.wrap_socket(raw, server_hostname=self.host)

        # 1. Read ServerInfo
        server_info_bytes = read_frame(self._sock)
        self.server_version = _extract_product_name(server_info_bytes)

        # 2. Login
        send_frame(self._sock, build_login_request(self.user, self.password))
        login_resp_bytes = read_frame(self._sock)
        login_state = _parse_login_state(login_resp_bytes)
        if login_state != self.LOGIN_SUCCESS:
            raise AS2AuthError(f"Login failed (state={login_state}) — check credentials")

    def close(self):
        if self._sock:
            try:
                send_frame(self._sock, build_quit_request(self.user))
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    # ------------------------------------------------------------------
    # API calls — each sends one request, reads one response
    # ------------------------------------------------------------------

    def list_partners(self, list_option: int = 0) -> list[dict]:
        """
        list_option: 0=ALL, 1=LOCAL_STATION, 2=NON_LOCAL, 3=BY_AS2_ID
        Returns list of partner dicts.
        """
        send_frame(self._sock, build_partner_list_request(list_option))
        resp = self._read_response()
        return _parse_partner_list(resp)

    def list_messages(
        self,
        limit: int = 50,
        start_time_ms: int = 0,
        end_time_ms: int = 0,
        show_finished: bool = True,
        show_pending: bool = True,
        show_stopped: bool = True,
        direction: int = 0,
        message_type: int = 0,
    ) -> list[dict]:
        send_frame(self._sock, build_message_overview_request(
            limit=limit,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            show_finished=show_finished,
            show_pending=show_pending,
            show_stopped=show_stopped,
            direction=direction,
            message_type=message_type,
        ))
        resp = self._read_response()
        return _parse_message_list(resp)

    def get_message_log(self, message_id: str) -> list[dict]:
        send_frame(self._sock, build_message_log_request(message_id))
        resp = self._read_response()
        return _parse_log_entries(resp)

    def get_message_payload(self, message_id: str) -> list[dict]:
        send_frame(self._sock, build_message_payload_request(message_id))
        resp = self._read_response()
        return _parse_payload_list(resp)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read_response(self) -> dict:
        data = read_frame(self._sock)
        reader = JavaReader(data)
        return reader.read_object()


# ---------------------------------------------------------------------------
# Parsers — turn deserialized Java object dicts into clean Python dicts
# ---------------------------------------------------------------------------

def _extract_product_name(data: bytes) -> str:
    for m in re.finditer(rb'[\x20-\x7e]{4,}', data):
        t = m.group().decode("ascii")
        if "mendelson" in t.lower():
            return t
    return "unknown"


def _parse_login_state(data: bytes) -> int:
    reader = JavaReader(data)
    obj = reader.read_object()
    if obj is None:
        return 0
    # state field is an int on LoginState
    return int(obj.get("state", 0))


def _parse_partner_list(obj: dict) -> list[dict]:
    if obj is None:
        return []
    raw_list = obj.get("list") or []
    return [_partner_to_dict(p) for p in raw_list if p]


def _partner_to_dict(p: dict) -> dict:
    if not isinstance(p, dict):
        return {}
    return {
        "name":             p.get("name"),
        "as2ident":         p.get("as2Identification"),
        "localstation":     bool(p.get("localStation")),
        "url":              p.get("url"),
        "mdnurl":           p.get("mdnURL"),
        "email":            p.get("email"),
        "subject":          p.get("subject"),
        "contenttype":      p.get("contentType"),
        "comment":          p.get("comment"),
        "signtype":         p.get("signType"),
        "encryptiontype":   p.get("encryptionType"),
        "compression":      p.get("compressionType"),
        "signedmdn":        bool(p.get("signedMDN")),
        "syncmdn":          bool(p.get("syncMDN")),
        "keepfilename":     bool(p.get("keepFilenameOnReceipt")),
        "enabledirpoll":    bool(p.get("enableDirPoll")),
        "pollinterval":     p.get("pollInterval"),
        "maxpollfiles":     p.get("maxPollFiles"),
    }


def _parse_message_list(obj: dict) -> list[dict]:
    if obj is None:
        return []
    raw_list = obj.get("list") or []
    return [_msginfo_to_dict(m) for m in raw_list if m]


_STATE_LABELS = {1: "ok", 2: "pending", 3: "error", 4: "stopped"}


def _msginfo_to_dict(m: dict) -> dict:
    if not isinstance(m, dict):
        return {}
    state = m.get("state")
    init_date = m.get("initDate")
    # initDate is a java.util.Date deserialized as its long timestamp
    init_ts = None
    if isinstance(init_date, dict):
        init_ts = init_date.get("fastTime") or init_date.get("time")
    elif isinstance(init_date, int):
        init_ts = init_date
    return {
        "messageid":      m.get("messageId"),
        "userdefinedid":  m.get("userdefinedId"),
        "senderid":       m.get("senderId"),
        "receiverid":     m.get("receiverId"),
        "direction":      m.get("direction"),
        "state":          state,
        "state_label":    _STATE_LABELS.get(state, "unknown"),
        "signtype":       m.get("signType"),
        "encryptiontype": m.get("encryptionType"),
        "compression":    m.get("compressionType"),
        "usestls":        bool(m.get("usesTLS")),
        "init_ts_ms":     init_ts,
        "subject":        m.get("subject"),
    }


def _parse_log_entries(obj: dict) -> list[dict]:
    if obj is None:
        return []
    raw_list = obj.get("list") or []
    result = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue
        result.append({
            "level":   entry.get("level"),
            "time_ms": entry.get("logTime") or entry.get("time"),
            "message": entry.get("message") or entry.get("logText"),
        })
    return result


def _parse_payload_list(obj: dict) -> list[dict]:
    if obj is None:
        return []
    raw_list = obj.get("list") or []
    result = []
    for p in raw_list:
        if not isinstance(p, dict):
            continue
        result.append({
            "originalfilename": p.get("originalFilename"),
            "payloadfilename":  p.get("payloadFilename"),
            "contenttype":      p.get("contentType"),
        })
    return result
