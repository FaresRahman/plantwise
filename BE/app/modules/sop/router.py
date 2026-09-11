from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.contracts import ChatToolSpec, register_tool
from app.core.db import get_db
from app.core.deps import get_current_user, get_tenant_id, require_role
from app.core.module_registry import ModuleRegistration, register_module
from app.core.upload_limits import enforce_upload_limit
from app.modules.sop import service
from app.modules.sop.schemas import (
    SopDocumentOut,
    SopQueryArgs,
)

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "sop", "status": "ok"}


@router.post("/documents", response_model=SopDocumentOut, status_code=201)
async def upload_document(
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    name: str | None = Form(None),
    tags: str = Form(""),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    # BRD §4.4: "document upload (PDF/DOCX; optional URL)" — exactly one of
    # file or url must be given; both resolve to the same (content, filename)
    # shape before entering the shared parse/chunk/embed pipeline below.
    if file and url:
        raise HTTPException(status_code=400, detail="Provide either a file or a URL, not both")
    if file:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Uploaded file has no filename")
        await enforce_upload_limit(file)
        content = await file.read()
        filename = file.filename
    elif url:
        try:
            content, filename = await service.fetch_url_content(url)
        except service.SopError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        raise HTTPException(status_code=400, detail="Provide either a file or a URL")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        document = await service.upload_document(
            db, tenant_id, user.id, filename, content, name, tag_list
        )
    except service.SopError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_audit(
        db,
        tenant_id,
        user.id,
        action="upload_sop_doc",
        entity_type="sop_document",
        entity_id=document.id,
        details=f"name={document.name} version={document.version}",
    )
    return document


@router.get("/documents", response_model=list[SopDocumentOut])
async def list_documents(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_tenant_id)):
    return await service.list_documents(db, tenant_id)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    try:
        await service.delete_document(db, tenant_id, document_id)
    except service.SopError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    await log_audit(
        db, tenant_id, user.id, action="delete_sop_doc", entity_type="sop_document", entity_id=document_id
    )
    return None


@router.get("/most-asked")
async def most_asked(
    limit: int = 5,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    _user=Depends(get_current_user),
):
    return await service.get_most_asked(db, tenant_id, limit=min(max(limit, 1), 20))


register_tool(
    ChatToolSpec(
        name="sop_query",
        description=(
            "Answers how/what procedure questions by retrieving relevant SOP document excerpts for "
            "this tenant and citing document + section. Use for lockout/tagout, safety, and other "
            "procedure questions. Returns found=False with no citations if nothing relevant exists."
        ),
        args_schema=SopQueryArgs,
        fn=service.sop_query_tool,
    )
)

register_module(
    ModuleRegistration(
        key="sop",
        prefix="sop",
        router=router,
        get_summary=service.get_summary,
        get_shift_contribution=None,  # SOP has no shift-report contribution
    )
)
