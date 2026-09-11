from sqlalchemy.ext.asyncio import AsyncSession

from app.core import module_registry
from app.core.contracts import ModuleSummary


async def get_all_summaries(db: AsyncSession, tenant_id: int) -> list[ModuleSummary]:
    """Loops every registered module and calls its get_summary, if it has one.
    This already works today against every module's stub summary — Dev A/B
    replace the stub bodies with real numbers, no change needed here.
    """
    from app.modules.notifications.service import check_missing_data

    # Opportunistic missing-data nudge check (BRD §5.4/§6.2) — no cron in v1,
    # so a dashboard load is the "simple scheduled check" the brief allows.
    # Deduped internally via ModuleFreshness.last_nudged_at, so this is safe
    # to call on every request.
    await check_missing_data(db, tenant_id)

    summaries: list[ModuleSummary] = []
    for registration in module_registry.MODULES:
        if registration.get_summary is None:
            continue
        summaries.append(await registration.get_summary(db, tenant_id))

    # Alerts/recommendations float to the top per the PRD's dashboard spec.
    summaries.sort(key=lambda s: (s.status != "critical", s.status != "warning", -(s.alerts_count or 0)))
    return summaries
