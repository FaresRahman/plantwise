from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models_shared import AuditLog


async def log_audit(
    db: AsyncSession,
    tenant_id: int,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    details: str | None = None,
) -> None:
    """Call this right after committing any config-mutating change: asset/line/
    item/characteristic CRUD, SOP document upload, user/role changes, alert
    settings, shift schedule config. Every module is expected to call this —
    it's not optional.
    """
    entry = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
    )
    db.add(entry)
    await db.commit()
