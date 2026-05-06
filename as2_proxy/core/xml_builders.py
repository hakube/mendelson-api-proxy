"""
Build well-formed XML request strings for every Mendelson AS2 XML API command.
"""

from xml.etree import ElementTree as ET


def _req(command: str) -> ET.Element:
    root = ET.Element("request")
    cmd = ET.SubElement(root, "command")
    cmd.set("name", command)
    return root


def _to_str(root: ET.Element) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


# ---------------------------------------------------------------------------
# Partners
# ---------------------------------------------------------------------------

def list_partners(name_filter: list[str] | None = None) -> str:
    root = _req("LIST PARTNER")
    for name in (name_filter or []):
        f = ET.SubElement(root, "filter")
        f.set("type", "name")
        f.text = name
    return _to_str(root)


def add_partner(partner: dict) -> str:
    root = _req("ADD PARTNER")
    _append_partner(root, partner)
    return _to_str(root)


def modify_partner(partner: dict) -> str:
    root = _req("MODIFY PARTNER")
    _append_partner(root, partner)
    return _to_str(root)


def delete_partner(as2_ids: list[str]) -> str:
    root = _req("DELETE PARTNER")
    for as2_id in as2_ids:
        id_el = ET.SubElement(root, "id")
        id_el.text = as2_id
    return _to_str(root)


def _append_partner(root: ET.Element, p: dict) -> None:
    partner = ET.SubElement(root, "partner")
    _cdata(partner, "name", p["name"])
    _cdata(partner, "as2ident", p["as2ident"])
    _cdata(partner, "contenttype", p.get("contenttype", "application/EDI-Consent"))
    _cdata(partner, "email", p.get("email", ""))
    _cdata(partner, "url", p.get("url", ""))
    _cdata(partner, "mdnurl", p.get("mdnurl", p.get("url", "")))
    _cdata(partner, "subject", p.get("subject", "AS2 message"))
    if p.get("cryptalias"):
        _cdata(partner, "cryptalias", p["cryptalias"])
    if p.get("signalias"):
        _cdata(partner, "signalias", p["signalias"])
    _cdata(partner, "overwritelocalstationsecurity", str(p.get("overwritelocalstationsecurity", False)).upper())
    ET.SubElement(partner, "compression").text = str(p.get("compression", 1))
    ET.SubElement(partner, "transferencoding").text = str(p.get("transferencoding", 1))
    ET.SubElement(partner, "encryptiontype").text = str(p.get("encryptiontype", 2))
    ET.SubElement(partner, "keepfilename").text = str(p.get("keepfilename", False)).lower()
    ET.SubElement(partner, "localstation").text = str(p.get("localstation", False)).lower()
    ET.SubElement(partner, "notifyreceive").text = str(p.get("notifyreceive", 0))
    ET.SubElement(partner, "notifyreceiveenabled").text = str(p.get("notifyreceiveenabled", False)).lower()
    ET.SubElement(partner, "notifysend").text = str(p.get("notifysend", 0))
    ET.SubElement(partner, "notifysendenabled").text = str(p.get("notifysendenabled", False)).lower()
    ET.SubElement(partner, "notifysendreceiveenabled").text = str(p.get("notifysendreceiveenabled", False)).lower()
    ET.SubElement(partner, "pollinterval").text = str(p.get("pollinterval", 30))
    ET.SubElement(partner, "signtype").text = str(p.get("signtype", 2))
    ET.SubElement(partner, "signedmdn").text = str(p.get("signedmdn", True)).lower()
    ET.SubElement(partner, "syncmdn").text = str(p.get("syncmdn", True)).lower()
    ET.SubElement(partner, "enabledirpoll").text = str(p.get("enabledirpoll", True)).lower()
    # HTTP auth placeholder (required by schema)
    for auth_type in ("standard", "asyncmdn"):
        auth_el = ET.SubElement(partner, "httpauthentication")
        auth_el.set("type", auth_type)
        ET.SubElement(auth_el, "enabled").text = "false"


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------

def add_certificate(alias: str, pem: str, target: str = "encsign") -> str:
    root = _req("ADD CERTIFICATE")
    ET.SubElement(root, "target").text = target
    ET.SubElement(root, "alias").text = alias
    ET.SubElement(root, "pem").text = pem
    return _to_str(root)


def delete_certificate(aliases: list[str], target: str = "encsign") -> str:
    root = _req("DELETE CERTIFICATE")
    ET.SubElement(root, "target").text = target
    for alias in aliases:
        ET.SubElement(root, "alias").text = alias
    return _to_str(root)


# ---------------------------------------------------------------------------
# Messages / Transmissions
# ---------------------------------------------------------------------------

def list_transmissions(max_age_seconds: int = 86400) -> str:
    root = _req("LIST TRANSMISSION")
    f = ET.SubElement(root, "filter")
    f.set("type", "maxageins")
    f.text = str(max_age_seconds)
    return _to_str(root)


def list_transmission_log(user_defined_id: str) -> str:
    root = _req("LIST TRANSMISSIONLOG")
    f = ET.SubElement(root, "filter")
    f.set("type", "userdefinedid")
    f.text = user_defined_id
    return _to_str(root)


def send_data(receiver_as2_id: str, payload_path: str, user_defined_id: str | None = None) -> str:
    root = _req("SEND DATA")
    ET.SubElement(root, "receiver").text = receiver_as2_id
    ET.SubElement(root, "file").text = payload_path
    if user_defined_id:
        ET.SubElement(root, "userdefinedid").text = user_defined_id
    return _to_str(root)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cdata(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.text = text
    return el
