"""Admin console is mostly a thin UI over endpoints owned by other modules
(auth for users/roles, notifications for alert settings, sop for document
management). This file only holds the two things that are genuinely
admin-only and don't belong elsewhere: user list/role/active management
(reading and mutating auth's User model directly, not duplicating its
data) and the per-module freshness overview.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import ROLES, User


class AdminError(Exception):
    pass


async def list_users(db: AsyncSession, tenant_id: int) -> list[User]:
    return list(await db.scalars(select(User).where(User.tenant_id == tenant_id)))


async def update_role(db: AsyncSession, tenant_id: int, user_id: int, role: str) -> User:
    if role not in ROLES:
        raise AdminError(f"Unknown role '{role}'")
    user = await db.scalar(select(User).where(User.tenant_id == tenant_id, User.id == user_id))
    if user is None:
        raise AdminError("User not found")
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


async def set_active(db: AsyncSession, tenant_id: int, user_id: int, is_active: bool) -> User:
    user = await db.scalar(select(User).where(User.tenant_id == tenant_id, User.id == user_id))
    if user is None:
        raise AdminError("User not found")
    user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    return user


async def get_freshness_overview(db: AsyncSession, tenant_id: int) -> list[dict]:
    from app.core.models_shared import ModuleFreshness

    rows = await db.scalars(select(ModuleFreshness).where(ModuleFreshness.tenant_id == tenant_id))
    return [
        {"module": r.module, "last_updated_at": r.last_updated_at, "expected_cadence_hours": r.expected_cadence_hours}
        for r in rows
    ]


async def list_audit_log(db: AsyncSession, tenant_id: int, limit: int = 200) -> list[dict]:
    """BRD §5.1.1: 'audit trail — who changed which configuration and who
    uploaded which data, with timestamps.' log_audit() has always written
    these rows; this is the read side so an Admin can actually see them,
    most-recent first.
    """
    from app.core.models_shared import AuditLog

    rows = list(
        await db.scalars(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    )
    user_ids = {r.user_id for r in rows if r.user_id is not None}
    emails: dict[int, str] = {}
    if user_ids:
        result = await db.execute(select(User.id, User.email).where(User.id.in_(user_ids)))
        emails = {row.id: row.email for row in result}

    return [
        {
            "id": r.id,
            "user_email": emails.get(r.user_id) if r.user_id is not None else None,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "details": r.details,
            "created_at": r.created_at,
        }
        for r in rows
    ]
