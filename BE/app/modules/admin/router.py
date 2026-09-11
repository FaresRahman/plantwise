from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.db import get_db
from app.core.deps import get_tenant_id, require_role
from app.core.module_registry import ModuleRegistration, register_module
from app.modules.admin import service
from app.modules.admin.schemas import ActiveUpdateRequest, AdminUserOut, AuditLogEntryOut, FreshnessRow, RoleUpdateRequest

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "admin", "status": "ok"}


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    _admin=Depends(require_role("admin")),
):
    return await service.list_users(db, tenant_id)


@router.patch("/users/{user_id}/role", response_model=AdminUserOut)
async def update_role(
    user_id: int,
    payload: RoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    admin=Depends(require_role("admin")),
):
    try:
        user = await service.update_role(db, tenant_id, user_id, payload.role)
    except service.AdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        db, tenant_id, admin.id, action="update_user_role", entity_type="user", entity_id=user_id,
        details=f"role={payload.role}",
    )
    return user


@router.patch("/users/{user_id}/active", response_model=AdminUserOut)
async def set_active(
    user_id: int,
    payload: ActiveUpdateRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    admin=Depends(require_role("admin")),
):
    try:
        user = await service.set_active(db, tenant_id, user_id, payload.is_active)
    except service.AdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        db, tenant_id, admin.id, action="set_user_active", entity_type="user", entity_id=user_id,
        details=f"is_active={payload.is_active}",
    )
    return user


@router.get("/freshness", response_model=list[FreshnessRow])
async def freshness(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    _admin=Depends(require_role("admin")),
):
    return await service.get_freshness_overview(db, tenant_id)


@router.get("/audit-log", response_model=list[AuditLogEntryOut])
async def audit_log(
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    _admin=Depends(require_role("admin")),
):
    return await service.list_audit_log(db, tenant_id, limit=min(max(limit, 1), 500))


register_module(
    ModuleRegistration(
        key="admin",
        prefix="admin",
        router=router,
        get_summary=None,
        get_shift_contribution=None,
    )
)
