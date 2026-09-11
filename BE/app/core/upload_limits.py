"""Shared upload-size enforcement.  Called from every CSV upload endpoint
so no single router silently allows an unbounded file."""

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024  # 1 MB — bounds how much of an oversized file we ever hold at once


async def enforce_upload_limit(file: UploadFile) -> None:
    """Check the file's size without ever buffering the whole thing at once.
    Raises 413 as soon as the cumulative size crosses MAX_UPLOAD_SIZE_MB —
    previously this called file.read() with no size argument first (loading
    the entire file into memory unconditionally) and only compared lengths
    afterward, so the "cap" did nothing to bound memory for a large/hostile
    upload; it just rejected it after already paying the cost. Rewinds the
    file so the caller can still read it from the start.
    """
    total = 0
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_BYTES:
            await file.seek(0)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit",
            )
    await file.seek(0)
