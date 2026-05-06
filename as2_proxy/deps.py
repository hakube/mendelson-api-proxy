"""
FastAPI dependency: provides a configured AS2XMLClient per request.
All settings are read from environment variables.

Required env vars:
  AS2_HOME      path to the Mendelson AS2 installation (contains as2.jar)
  AS2_HOST      hostname/IP of the AS2 server (default: localhost)
  AS2_PORT      client-server port (default: 1234)
  AS2_USER      admin username (default: admin)
  AS2_PASSWORD  admin password (default: admin)

Optional:
  AS2_CLIENT_ID version string the server expects (default: mendelson AS2 2024 build 598)
  AS2_JAVA      path to java executable (default: java)
  AS2_TIMEOUT   subprocess timeout in seconds (default: 30)
"""

import os
from .core.xml_client import AS2XMLClient

_client: AS2XMLClient | None = None


def get_client() -> AS2XMLClient:
    global _client
    if _client is None:
        _client = AS2XMLClient(
            host=os.environ.get("AS2_HOST", "localhost"),
            port=int(os.environ.get("AS2_PORT", "1234")),
            user=os.environ.get("AS2_USER", "admin"),
            password=os.environ.get("AS2_PASSWORD", "admin"),
            client_id=os.environ.get("AS2_CLIENT_ID", "mendelson AS2 2024 build 598"),
            timeout=float(os.environ.get("AS2_TIMEOUT", "30")),
            as2_home=os.environ.get("AS2_HOME", ""),
            java_exec=os.environ.get("AS2_JAVA", "java"),
        )
    return _client
