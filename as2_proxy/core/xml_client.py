"""
AS2XMLClient — delegates all server operations to the AS2Bridge Java subprocess,
which speaks the native Mendelson TLS + zlib + Java-serialization protocol.
"""

import asyncio
import glob as _glob
import json
import os
import subprocess

_BRIDGE_CLASS = "AS2Bridge"


class AS2XMLClient:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 1234,
        user: str = "admin",
        password: str = "admin",
        timeout: float = 30.0,
        as2_home: str = "",
        java_exec: str = "java",
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.timeout = timeout
        self.as2_home = as2_home or _default_as2_home()
        self.java_exec = java_exec

    def _run(self, *extra_args: str) -> dict:
        cp = _build_classpath(self.as2_home)
        cmd = [
            self.java_exec, "-cp", cp, _BRIDGE_CLASS,
            self.host, str(self.port), self.user, self.password,
            *extra_args,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=self.as2_home,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"Bridge exited {result.returncode}")
        return json.loads(result.stdout.strip())

    def ping(self) -> str:
        return self._run("ping").get("status", "ok")

    def list_partners(self) -> list[dict]:
        return self._run("list_partners")["partners"]

    def list_messages(
        self,
        limit: int = 50,
        direction: int = 0,
        start_ms: int = 0,
        end_ms: int = 0,
        show_finished: bool = True,
        show_pending: bool = True,
        show_stopped: bool = True,
        message_type: int = 0,
    ) -> list[dict]:
        data = self._run(
            "list_messages",
            str(limit),
            str(direction),
            str(start_ms),
            str(end_ms),
            str(show_finished).lower(),
            str(show_pending).lower(),
            str(show_stopped).lower(),
            str(message_type),
        )
        return data["messages"]

    def get_message_log(self, message_id: str) -> list[dict]:
        return self._run("get_message_log", message_id)["log"]

    def get_message_payload(self, message_id: str) -> list[dict]:
        return self._run("get_message_payload", message_id)["payloads"]

    def download_payload(self, message_id: str) -> tuple[bytes, str, str]:
        """Returns (data, content_type, original_filename)."""
        cp = _build_classpath(self.as2_home)
        cmd = [
            self.java_exec, "-cp", cp, _BRIDGE_CLASS,
            self.host, str(self.port), self.user, self.password,
            "download_payload", message_id,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=self.timeout,
            cwd=self.as2_home,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode(errors="replace").strip()
                               or f"Bridge exited {result.returncode}")
        # Metadata lines come on stderr; raw bytes on stdout
        content_type = "application/octet-stream"
        original_filename = "payload"
        for line in result.stderr.decode(errors="replace").splitlines():
            if line.startswith("CONTENT_TYPE:"):
                content_type = line[len("CONTENT_TYPE:"):]
            elif line.startswith("ORIGINAL_FILENAME:"):
                original_filename = line[len("ORIGINAL_FILENAME:"):]
        return result.stdout, content_type, original_filename

    async def download_payload_async(self, message_id: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.download_payload, message_id)

    def send_message(
        self,
        sender: str,
        receiver: str,
        file_path: str,
        user_defined_id: str = "--",
        subject: str | None = None,
    ) -> dict:
        """Trigger an outbound send via the free AS2Send CLI."""
        cp = _build_classpath(self.as2_home)
        import tempfile
        from xml.etree import ElementTree as ET
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            resp_path = f.name
        cmd = [
            self.java_exec, "-cp", cp,
            "de.mendelson.comm.as2.api.AS2Send",
            "-user", self.user, "-password", self.password,
            "-host", self.host, "-port", str(self.port),
            "-sender", sender, "-receiver", receiver,
            "-file", file_path, "-userdefinedid", user_defined_id,
            "-response", resp_path,
        ]
        if subject is not None:
            cmd += ["-subject", subject]
        try:
            subprocess.run(cmd, capture_output=True, text=True,
                           timeout=self.timeout, cwd=self.as2_home, check=False)
            with open(resp_path) as f:
                xml = f.read()
            root = ET.fromstring(_extract_xml(xml))
            return _parse_send_response(root)
        finally:
            try:
                os.unlink(resp_path)
            except OSError:
                pass

    # Async wrappers
    async def list_partners_async(self):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.list_partners)

    async def list_messages_async(self, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.list_messages(**kwargs))

    async def get_message_log_async(self, message_id: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_message_log, message_id)

    async def get_message_payload_async(self, message_id: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_message_payload, message_id)

    async def send_message_async(self, subject: str | None = None, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.send_message(subject=subject, **kwargs))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_as2_home() -> str:
    env = os.environ.get("AS2_HOME")
    if env:
        return env
    return str(os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    ))


def _build_classpath(as2_home: str) -> str:
    home = as2_home.rstrip("/")
    jars = [f"{home}/as2.jar", home]  # home for AS2Bridge.class
    for pattern in (
        f"{home}/jlib/*.jar",
        f"{home}/jlib/mina/*.jar",
        f"{home}/jlib/oshi/*.jar",
        f"{home}/jlib/jackson/*.jar",  # needed for LogEntry deserialization
        f"{home}/jlib/httpclient/*.jar",
        f"{home}/jlib/db/*.jar",
    ):
        jars.extend(sorted(_glob.glob(pattern)))
    return os.pathsep.join(jars)


def _extract_xml(text: str) -> str:
    for marker in ("<?xml", "<response"):
        idx = text.find(marker)
        if idx != -1:
            return text[idx:]
    raise ValueError(f"No XML in output: {text[:200]}")


def _parse_send_response(root) -> dict:
    order = root.find("order")
    if order is None:
        return {"state": "UNKNOWN", "details": ""}
    return {
        "state":   (order.findtext("state") or "").strip(),
        "details": (order.findtext("details") or "").strip(),
    }
