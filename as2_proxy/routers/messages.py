import os
import tempfile

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from typing import Annotated

from ..deps import get_client
from ..core.xml_client import AS2XMLClient

router = APIRouter(prefix="/messages", tags=["messages"])


_SERVER_MAX = 1000  # hard limit the Mendelson server honours


@router.get("/")
async def list_messages(
    client: Annotated[AS2XMLClient, Depends(get_client)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    direction: int = Query(default=0, description="0=all 1=inbound 2=outbound"),
    show_finished: bool = Query(default=True, description="Include finished messages"),
    show_pending: bool = Query(default=True, description="Include pending messages"),
    show_stopped: bool = Query(default=True, description="Include stopped/error messages"),
    message_type: int = Query(default=0, description="0=all 1=AS2 2=CEM"),
    start_ms: int = Query(default=0, description="Filter from this Unix timestamp (ms)"),
    end_ms: int = Query(default=0, description="Filter up to this Unix timestamp (ms)"),
):
    # We need page*page_size records to slice the requested page. The server
    # caps at 1000, so pages beyond that window are rejected.
    fetch_needed = page * page_size
    if fetch_needed > _SERVER_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Page {page} with page_size {page_size} requires {fetch_needed} records "
                   f"but the server maximum is {_SERVER_MAX}. "
                   f"Use start_ms/end_ms to narrow the time window.",
        )
    try:
        # Fetch one extra so we can report has_more accurately.
        messages = await client.list_messages_async(
            limit=fetch_needed + 1,
            direction=direction,
            show_finished=show_finished,
            show_pending=show_pending,
            show_stopped=show_stopped,
            message_type=message_type,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        # Server returns oldest-first; reverse for newest-first default.
        messages.sort(key=lambda m: m.get("initdate") or 0, reverse=True)
        start = (page - 1) * page_size
        page_items = messages[start: start + page_size]
        has_more = len(messages) > fetch_needed
        return {
            "messages": page_items,
            "page": page,
            "page_size": page_size,
            "count": len(page_items),
            "has_more": has_more,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{message_id}/log")
async def get_message_log(
    message_id: str,
    client: Annotated[AS2XMLClient, Depends(get_client)],
):
    try:
        return {"log": await client.get_message_log_async(message_id)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{message_id}/payload")
async def get_message_payload(
    message_id: str,
    client: Annotated[AS2XMLClient, Depends(get_client)],
):
    try:
        return {"payloads": await client.get_message_payload_async(message_id)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{message_id}/payload/download")
async def download_payload(
    message_id: str,
    client: Annotated[AS2XMLClient, Depends(get_client)],
):
    try:
        data, content_type, original_filename = await client.download_payload_async(message_id)
        safe_filename = original_filename.replace('"', '').replace("'", "")
        return Response(
            content=data,
            media_type=content_type,
            headers={"Content-Disposition": f'inline; filename="{safe_filename}"'},
        )
    except RuntimeError as e:
        detail = str(e)
        if "FileNotFoundException" in detail:
            raise HTTPException(status_code=404, detail="Payload file not found on server (may have been deleted or moved)")
        raise HTTPException(status_code=502, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/send", status_code=202)
async def send_message(
    client: Annotated[AS2XMLClient, Depends(get_client)],
    file: UploadFile,
    sender: Annotated[str, Form()],
    receiver: Annotated[str, Form()],
    user_defined_id: Annotated[str, Form()] = "--",
    subject: Annotated[str | None, Form()] = None,
):
    suffix = os.path.splitext(file.filename or "payload")[1] or ".dat"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(await file.read())
        tmp.close()
        return await client.send_message_async(
            sender=sender,
            receiver=receiver,
            file_path=tmp.name,
            user_defined_id=user_defined_id,
            subject=subject,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
