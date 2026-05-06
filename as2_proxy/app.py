from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import partners, messages, certificates
from .deps import get_client

app = FastAPI(
    title="Mendelson AS2 Proxy API",
    description="REST API speaking the native Mendelson AS2 client-server protocol",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(partners.router)
app.include_router(messages.router)
app.include_router(certificates.router)


@app.get("/health")
def health():
    try:
        client = get_client()
        version = client.ping()
        return {"status": "ok", "server": version}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
