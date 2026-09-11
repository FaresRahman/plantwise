"""Shared staleness check for chat tools. PRD §4.8/§5.3 hard rule: "if the
data isn't present or is stale, it says so" — every data-query chat tool
should be able to tell the model whether the numbers it just returned are
current, not just whether they exist at all.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models_shared import ModuleFreshness


async def get_freshness(db: AsyncSession, tenant_id: int, module: str) -> dict:
    """Returns {"last_updated_at": iso str | None, "is_stale": bool} for a
    module. No ModuleFreshness row at all (nothing ever uploaded) counts as
    stale — there's no "current" data to speak of.
    """
    freshness = await db.scalar(
        select(ModuleFreshness).where(ModuleFreshness.tenant_id == tenant_id, ModuleFreshness.module == module)
    )
    if freshness is None:
        return {"last_updated_at": None, "is_stale": True}
    age_hours = (datetime.utcnow() - freshness.last_updated_at).total_seconds() / 3600
    return {
        "last_updated_at": freshness.last_updated_at.isoformat(),
        "is_stale": age_hours > freshness.expected_cadence_hours,
    }
