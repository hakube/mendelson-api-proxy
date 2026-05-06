from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Annotated

from ..deps import get_client
from ..core.xml_client import AS2XMLClient

router = APIRouter(prefix="/partners", tags=["partners"])


@router.get("/")
async def list_partners(client: Annotated[AS2XMLClient, Depends(get_client)]):
    try:
        return {"partners": await client.list_partners_async()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/local")
async def list_local_stations(client: Annotated[AS2XMLClient, Depends(get_client)]):
    try:
        partners = await client.list_partners_async()
        return {"partners": [p for p in partners if p.get("localstation")]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
