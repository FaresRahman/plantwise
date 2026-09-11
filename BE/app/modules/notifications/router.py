from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.db import get_db
from app.core.deps import get_tenant_id, require_role
from app.core.module_registry import ModuleRegistration, register_module
from app.modules.notifications import service
from app.modules.notifications.schemas import AlertSettingIn, AlertSettingOut

# Modules with alert settings surfaced in the admin console. Any module can
# technically be passed to trigger_generic_alert; this list just drives the
# "known modules" list the settings UI renders rows for. "missing_data" and
# "daily_digest" are pseudo-modules: one tenant-wide toggle each, not tied to
# any single module's own data (§5.4/§6.2 and §5.6 respectively).
KNOWN_MODULES = ("predictive_maintenance", "inventory", "quality", "missing_data", "daily_digest")

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "notifications", "status": "ok"}


@router.get("/settings", response_model=list[AlertSettingOut])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin")),
):
    return [await service.get_setting(db, tenant_id, module) for module in KNOWN_MODULES]


@router.get("/settings/{module}", response_model=AlertSettingOut)
async def get_setting(
    module: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin")),
):
    return await service.get_setting(db, tenant_id, module)


@router.put("/settings/{module}", response_model=AlertSettingOut)
async def put_setting(
    module: str,
    payload: AlertSettingIn,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    result = await service.upsert_setting(
        db, tenant_id, module, payload.urgency_threshold, payload.enabled, payload.recipients
    )
    await log_audit(
        db,
        tenant_id,
        user.id,
        action="update_alert_setting",
        entity_type="alert_setting",
        entity_id=module,
        details=f"enabled={payload.enabled} threshold={payload.urgency_threshold}",
    )
    return result


@router.post("/digest/send")
async def send_digest_now(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    result = await service.send_daily_digest(db, tenant_id)
    await log_audit(db, tenant_id, user.id, action="send_daily_digest", entity_type="alert_setting", details=str(result))
    return result


register_module(
    ModuleRegistration(
        key="notifications",
        prefix="notifications",
        router=router,
        get_summary=None,  # no dashboard card of its own — surfaced via admin console
        get_shift_contribution=None,
    )
)
