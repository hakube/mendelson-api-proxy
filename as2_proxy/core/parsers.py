"""
Parse Mendelson AS2 XML API responses into plain dicts.
"""

from xml.etree import ElementTree as ET


def parse_partners(root: ET.Element) -> list[dict]:
    partners = []
    for p in root.findall("partner"):
        partners.append(_parse_partner(p))
    return partners


def _parse_partner(p: ET.Element) -> dict:
    def txt(tag: str) -> str:
        return (p.findtext(tag) or "").strip()

    def boolean(tag: str) -> bool:
        return txt(tag).lower() == "true"

    def integer(tag: str) -> int | None:
        v = txt(tag)
        return int(v) if v.lstrip("-").isdigit() else None

    auth_blocks = {}
    for auth in p.findall("httpauthentication"):
        atype = auth.get("type", "")
        auth_blocks[atype] = {
            "enabled": (auth.findtext("enabled") or "").lower() == "true",
            "user": (auth.findtext("user") or "").strip(),
        }

    return {
        "name": txt("name"),
        "as2ident": txt("as2ident"),
        "localstation": boolean("localstation"),
        "url": txt("url"),
        "mdnurl": txt("mdnurl"),
        "email": txt("email"),
        "contenttype": txt("contenttype"),
        "subject": txt("subject"),
        "cryptalias": txt("cryptalias"),
        "signalias": txt("signalias"),
        "signtype": integer("signtype"),
        "encryptiontype": integer("encryptiontype"),
        "compression": integer("compression"),
        "transferencoding": integer("transferencoding"),
        "signedmdn": boolean("signedmdn"),
        "syncmdn": boolean("syncmdn"),
        "keepfilename": boolean("keepfilename"),
        "enabledirpoll": boolean("enabledirpoll"),
        "pollinterval": integer("pollinterval"),
        "httpauthentication": auth_blocks,
    }


def parse_transmissions(root: ET.Element) -> list[dict]:
    messages = []
    for m in root.findall("messageinfo"):
        messages.append(_parse_messageinfo(m))
    return messages


def parse_transmission_log(root: ET.Element) -> dict:
    message = None
    m = root.find("messageinfo")
    if m is not None:
        message = _parse_messageinfo(m)

    logs = []
    for entry in root.findall("logentry"):
        logs.append({
            "level": entry.get("level"),
            "time": entry.get("time"),
            "text": (entry.text or "").strip(),
        })

    return {"message": message, "log": logs}


def _parse_messageinfo(m: ET.Element) -> dict:
    def txt(tag: str) -> str:
        return (m.findtext(tag) or "").strip()

    return {
        "id": txt("id"),
        "userdefinedid": txt("userdefinedid"),
        "senderid": txt("senderid"),
        "receiverid": txt("receiverid"),
        "signtype": _int_or_none(txt("signtype")),
        "encryptiontype": _int_or_none(txt("encryptiontype")),
        "compressiontype": _int_or_none(txt("compressiontype")),
        "state": _int_or_none(txt("state")),
        "state_label": _state_label(txt("state")),
    }


def _int_or_none(v: str) -> int | None:
    return int(v) if v.lstrip("-").isdigit() else None


# State codes observed in the XML API samples
_STATE_LABELS = {
    1: "ok",
    2: "pending",
    3: "error",
    4: "stopped",
}


def _state_label(v: str) -> str:
    try:
        return _STATE_LABELS.get(int(v), "unknown")
    except (ValueError, TypeError):
        return "unknown"
