"""
Certificate management is not yet implemented natively.
The XML_API plugin (which provides ADD/DELETE CERTIFICATE) is paywalled.
Implementing it natively requires reverse-engineering the PartnerModificationRequest
with certificate data embedded — future work.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/certificates", tags=["certificates"])


@router.get("/")
def certificates_info():
    return {
        "note": "Certificate management via native protocol is not yet implemented. "
                "Use the Mendelson AS2 admin UI or XML_API plugin for certificate operations."
    }
