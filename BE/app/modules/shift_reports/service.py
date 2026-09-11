from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import module_registry
from app.core.contracts import ModuleSummary
from app.core.dimension_resolver import resolve
from app.core.email import send_email
from app.core.ingestion import CSVSpec, ColumnSpec
from app.modules.shift_reports.models import ShiftReport, ShiftSchedule

MAX_QUERY_LIMIT = 20


async def compile_contributions(db: AsyncSession, tenant_id: int, start: datetime, end: datetime) -> list[dict]:
    """Fans out to every registered module's get_shift_contribution
    (Production/Quality/Predictive-Maintenance/Inventory all implement it for
    real; SOP deliberately doesn't — it has no shift-window contribution)
    and collects each into one list for the handover.
    """
    contributions = []
    for registration in module_registry.MODULES:
        if registration.get_shift_contribution is None:
            continue
        contributions.append((await registration.get_shift_contribution(db, tenant_id, start, end)).model_dump())
    return contributions


def _resolve_window(
    schedule: ShiftSchedule | None,
    window_start: datetime | None,
    window_end: datetime | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    if window_start and window_end:
        return window_start, window_end
    if schedule is None:
        raise ValueError("Either a shift_schedule_id or an explicit window_start/window_end is required")

    # Anchored to the same UTC "now" the scheduler used to decide whether to
    # fire (passed in explicitly) rather than independently calling naive,
    # server-local `date.today()` — those two could disagree near midnight
    # or on a host not running in UTC, silently shifting which calendar
    # day's data a shift report covers.
    today = (now or datetime.now(timezone.utc)).date()
    start = datetime.combine(today, schedule.start_time)
    end = datetime.combine(today, schedule.end_time)
    if end <= start:  # overnight shift (e.g. 22:00 -> 06:00)
        end += timedelta(days=1)
    return start, end


def _next_shift_actions(contributions: list[dict]) -> list[str]:
    seen: set[str] = set()
    actions: list[str] = []
    for c in contributions:
        for item in c.get("open_items", []):
            if item not in seen:
                seen.add(item)
                actions.append(item)
    return actions


def _render_report_html(window_start: datetime, window_end: datetime, contributions: list[dict], actions: list[str]) -> str:
    sections = "".join(
        f"<h3>{c['module'].replace('_', ' ').title()}</h3><p>{c.get('summary_text') or 'No update.'}</p>"
        for c in contributions
    )
    action_items = "".join(f"<li>{a}</li>" for a in actions) or "<li>No outstanding actions.</li>"
    return (
        f"<h2>Shift Report — {window_start.strftime('%Y-%m-%d %H:%M')} to {window_end.strftime('%Y-%m-%d %H:%M')}</h2>"
        f"{sections}<h3>Next-Shift Actions</h3><ul>{action_items}</ul>"
    )


# ---------------------------------------------------------------------------
# Shift schedule CSV config
# ---------------------------------------------------------------------------

SHIFT_SCHEDULE_CSV_SPEC = CSVSpec(
    module="shift_reports",
    columns=[
        ColumnSpec(name="name", dtype="str"),
        ColumnSpec(name="start_time", dtype="str"),  # "HH:MM" format
        ColumnSpec(name="end_time", dtype="str"),     # "HH:MM" format
        ColumnSpec(name="areas", dtype="str", required=False),
        ColumnSpec(name="recipients", dtype="str", required=False),
    ],
)


def _parse_time(value: str):
    """Parse 'HH:MM' string into a datetime.time object."""
    from datetime import time

    parts = str(value).strip().split(":")
    return time(int(parts[0]), int(parts[1]))


def _parse_semicolon_list(value):
    if not value or not str(value).strip():
        return []
    return [s.strip() for s in str(value).split(";") if s.strip()]


async def commit_shift_schedules_config(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> tuple[int, int]:
    """Insert shift schedules from CSV (insert-only, no unique key)."""
    created = 0
    for row in valid_rows:
        db.add(ShiftSchedule(
            tenant_id=tenant_id,
            name=row["name"],
            start_time=_parse_time(row["start_time"]),
            end_time=_parse_time(row["end_time"]),
            areas=_parse_semicolon_list(row.get("areas")),
            recipients=_parse_semicolon_list(row.get("recipients")),
        ))
        created += 1
    await db.commit()
    return created, 0  # (created, updated=0)


async def create_schedule(db: AsyncSession, tenant_id: int, payload) -> ShiftSchedule:
    schedule = ShiftSchedule(tenant_id=tenant_id, **payload.model_dump())
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


async def list_schedules(db: AsyncSession, tenant_id: int) -> list[ShiftSchedule]:
    return list(await db.scalars(select(ShiftSchedule).where(ShiftSchedule.tenant_id == tenant_id)))


async def update_schedule(db: AsyncSession, tenant_id: int, schedule_id: int, payload) -> ShiftSchedule:
    schedule = await db.scalar(
        select(ShiftSchedule).where(ShiftSchedule.tenant_id == tenant_id, ShiftSchedule.id == schedule_id)
    )
    if schedule is None:
        raise ValueError("Shift schedule not found")
    for key, value in payload.model_dump().items():
        setattr(schedule, key, value)
    await db.commit()
    await db.refresh(schedule)
    return schedule


async def delete_schedule(db: AsyncSession, tenant_id: int, schedule_id: int) -> None:
    schedule = await db.scalar(
        select(ShiftSchedule).where(ShiftSchedule.tenant_id == tenant_id, ShiftSchedule.id == schedule_id)
    )
    if schedule is None:
        raise ValueError("Shift schedule not found")
    await db.delete(schedule)
    await db.commit()


async def generate_report(
    db: AsyncSession,
    tenant_id: int,
    shift_schedule_id: int | None,
    window_start: datetime | None,
    window_end: datetime | None,
    now: datetime | None = None,
) -> ShiftReport:
    schedule = None
    if shift_schedule_id is not None:
        schedule = await db.scalar(
            select(ShiftSchedule).where(ShiftSchedule.tenant_id == tenant_id, ShiftSchedule.id == shift_schedule_id)
        )
        if schedule is None:
            raise ValueError("Shift schedule not found")

    start, end = _resolve_window(schedule, window_start, window_end, now=now)
    contributions = await compile_contributions(db, tenant_id, start, end)
    actions = _next_shift_actions(contributions)

    report = ShiftReport(
        tenant_id=tenant_id,
        shift_schedule_id=shift_schedule_id,
        window_start=start,
        window_end=end,
        compiled_content=contributions,
        next_shift_actions=actions,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    if schedule and schedule.recipients:
        send_email(
            to=schedule.recipients,
            subject=f"Shift Report — {schedule.name} ({start.strftime('%Y-%m-%d')})",
            html_body=_render_report_html(start, end, contributions, actions),
        )

    return report


async def list_reports(db: AsyncSession, tenant_id: int) -> list[ShiftReport]:
    return list(
        await db.scalars(
            select(ShiftReport).where(ShiftReport.tenant_id == tenant_id).order_by(ShiftReport.created_at.desc())
        )
    )


async def get_report(db: AsyncSession, tenant_id: int, report_id: int) -> ShiftReport:
    report = await db.scalar(
        select(ShiftReport).where(ShiftReport.tenant_id == tenant_id, ShiftReport.id == report_id)
    )
    if report is None:
        raise ValueError("Shift report not found")
    return report


def render_report_text(report: ShiftReport, schedule_name: str | None) -> str:
    """Plain-text rendering for the exportable archive (BRD §5.7), matching
    the handover format shown in §4.6's own example — same content the
    dashboard/email already show, just a downloadable file.
    """
    label = f"Shift Handover — {schedule_name}" if schedule_name else "Shift Handover"
    lines = [
        f"{label} ({report.window_start.strftime('%Y-%m-%d %H:%M')}–{report.window_end.strftime('%H:%M')})",
        "",
    ]
    for c in report.compiled_content:
        lines.append(f"{c['module'].replace('_', ' ').title()}: {c.get('summary_text') or 'No update.'}")
    lines.append("")
    lines.append("Next-shift actions:")
    if report.next_shift_actions:
        lines.extend(f"({i}) {a}" for i, a in enumerate(report.next_shift_actions, start=1))
    else:
        lines.append("None outstanding.")
    return "\n".join(lines)


async def get_summary(db: AsyncSession, tenant_id: int) -> ModuleSummary:
    from sqlalchemy import func

    total_reports = await db.scalar(
        select(func.count()).select_from(ShiftReport).where(ShiftReport.tenant_id == tenant_id)
    ) or 0
    latest = await db.scalar(
        select(ShiftReport)
        .where(ShiftReport.tenant_id == tenant_id)
        .order_by(ShiftReport.created_at.desc())
        .limit(1)
    )
    if latest is None:
        return ModuleSummary(
            module="shift_reports",
            title="Shift Reports",
            status="ok",
            headline="No shift reports generated yet",
            metrics=[{"label": "Reports generated", "value": str(total_reports)}],
            drilldown_path="/shift-reports",
        )
    return ModuleSummary(
        module="shift_reports",
        title="Shift Reports",
        status="ok",
        headline=f"Latest report covers {latest.window_start.strftime('%Y-%m-%d %H:%M')}-{latest.window_end.strftime('%H:%M')}",
        metrics=[
            {"label": "Reports generated", "value": str(total_reports)},
            {"label": "Next-shift actions", "value": str(len(latest.next_shift_actions))},
        ],
        last_updated_at=latest.created_at,
        is_stale=False,
        drilldown_path="/shift-reports",
    )


async def shift_reports_query_tool(
    db: AsyncSession, tenant_id: int, schedule_name: str | None = None, limit: int = 5
) -> dict:
    """Structured-query chat tool: filter/limit only, no SQL from the model.
    Proves the SchemaContextProvider + dimension_resolver pattern end-to-end
    on real data — Dev A's four modules register the equivalent tool the
    same way once their tables exist.
    """
    capped_limit = min(max(limit, 1), MAX_QUERY_LIMIT)
    schedules = await list_schedules(db, tenant_id)

    schedule_id: int | None = None
    if schedule_name:
        result = resolve(schedule_name, [s.name for s in schedules])
        if result.needs_clarification:
            return {
                "found": False,
                "needs_clarification": True,
                "candidates": result.candidates,
                "message": f"Did you mean one of: {', '.join(result.candidates)}?",
            }
        if result.matched is None:
            return {
                "found": False,
                "message": f"No shift schedule named '{schedule_name}' exists for this plant.",
            }
        schedule_id = next(s.id for s in schedules if s.name == result.matched)

    reports = await list_reports(db, tenant_id)
    if schedule_id is not None:
        reports = [r for r in reports if r.shift_schedule_id == schedule_id]
    reports = reports[:capped_limit]

    return {
        "found": len(reports) > 0,
        "reports": [
            {
                "window_start": r.window_start.isoformat(),
                "window_end": r.window_end.isoformat(),
                # Per-module summary lines (production/quality/maintenance/
                # inventory) — without this, "summarize the last shift"
                # (PRD §4.6's own example) could only ever answer with the
                # bare next-shift-actions list, never the actual handover.
                "modules": [
                    {"module": c["module"], "summary": c.get("summary_text")} for c in r.compiled_content
                ],
                "next_shift_actions": r.next_shift_actions,
            }
            for r in reports
        ],
    }
