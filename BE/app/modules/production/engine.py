"""OEE / downtime-attribution compute. See DEV_BRIEF_SELF.md section 5.2 and
the precise algorithm in the task prompt (supersedes 5.2).

Timezone convention: this whole module works in naive UTC datetimes (matches
the plain `DateTime` columns on OutputLog/Line and `pd.to_datetime(...)
.to_pydatetime()` from the CSV ingestion engine, which also yields naive
datetimes). Don't pass timezone-aware datetimes into these functions.
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Line, OutputLog


async def compute_line_metrics(db: AsyncSession, tenant_id: int, line_id: int, start: datetime, end: datetime) -> dict:
    """OEE + downtime pareto for one line (numeric PK) within [start, end).

    Returns {"error": "line not found"} if the line doesn't belong to this
    tenant. Ratios (availability/performance/quality/oee) are 0..1, rounded to
    3 decimals; the FE/service layer formats these as percentages for display.
    """
    line = await db.scalar(select(Line).where(Line.tenant_id == tenant_id, Line.id == line_id))
    if not line:
        return {"error": "line not found"}

    rows = (
        await db.scalars(
            select(OutputLog).where(
                OutputLog.tenant_id == tenant_id,
                OutputLog.line_id == line_id,
                OutputLog.timestamp >= start,
                OutputLog.timestamp < end,
            )
        )
    ).all()

    planned_time_minutes = (end - start).total_seconds() / 60
    downtime_minutes = sum(r.downtime_minutes or 0.0 for r in rows)
    run_time_minutes = max(0.0, planned_time_minutes - downtime_minutes)
    total_units = sum(r.units_produced or 0 for r in rows)
    good_units = sum(r.units_good or 0 for r in rows)
    reject_units = sum(r.units_reject or 0 for r in rows)

    availability = run_time_minutes / planned_time_minutes if planned_time_minutes > 0 else 0.0
    performance = (
        (line.ideal_cycle_time_seconds * total_units / 60) / run_time_minutes if run_time_minutes > 0 else 0.0
    )
    quality = good_units / total_units if total_units > 0 else 1.0
    oee = availability * performance * quality
    gap_to_target = total_units - line.shift_target_units

    pareto_acc: dict[tuple[str, str], float] = {}
    for r in rows:
        if r.downtime_minutes and r.downtime_minutes > 0:
            key = (r.station_id, r.downtime_reason or "unspecified")
            pareto_acc[key] = pareto_acc.get(key, 0.0) + r.downtime_minutes
    downtime_pareto = sorted(
        (
            {"station_id": station, "downtime_reason": reason, "downtime_minutes": round(minutes, 1)}
            for (station, reason), minutes in pareto_acc.items()
        ),
        key=lambda d: d["downtime_minutes"],
        reverse=True,
    )

    return {
        "line_id": line.id,
        "line_code": line.line_code,
        "line_name": line.name,
        "planned_time_minutes": round(planned_time_minutes, 1),
        "downtime_minutes": round(downtime_minutes, 1),
        "run_time_minutes": round(run_time_minutes, 1),
        "total_units": total_units,
        "good_units": good_units,
        "reject_units": reject_units,
        "availability": round(availability, 3),
        "performance": round(performance, 3),
        "quality": round(quality, 3),
        "oee": round(oee, 3),
        "shift_target_units": line.shift_target_units,
        "gap_to_target": gap_to_target,
        "downtime_pareto": downtime_pareto,
        # BRD §5.2: "missing expected data shown as a gap, not a zero" — lets
        # callers distinguish "no output logged for this window yet" from a
        # genuine 0%/behind-target reading, which otherwise look identical.
        "has_data": len(rows) > 0,
    }


async def compute_oee_history(db: AsyncSession, tenant_id: int, line_id: int, days: int, end: datetime) -> list[dict]:
    """Per-day OEE/availability/performance/quality for the last `days` days
    up to `end`, for BRD §5.7's "production/OEE over time" trend history.
    Each point is computed by the same compute_line_metrics used for the
    live snapshot — just called once per day-window — so the numbers always
    reconcile with the intra-day figures rather than being a separate,
    divergent computation.
    """
    points = []
    for offset in range(days - 1, -1, -1):
        day_end = end - timedelta(days=offset)
        day_start = day_end - timedelta(days=1)
        metrics = await compute_line_metrics(db, tenant_id, line_id, day_start, day_end)
        if "error" in metrics:
            return []
        points.append(
            {
                "date": day_start.date().isoformat(),
                "oee": metrics["oee"],
                "availability": metrics["availability"],
                "performance": metrics["performance"],
                "quality": metrics["quality"],
                "total_units": metrics["total_units"],
                # A day's target is one shift's worth — shift_target_units is
                # already a per-shift figure, so it maps cleanly onto a
                # single day bucket without needing a separate rate field.
                "shift_target_units": metrics["shift_target_units"],
            }
        )
    return points


async def get_downtime_events(
    db: AsyncSession, tenant_id: int, line_id: str, start: datetime, end: datetime
) -> list[dict]:
    """Downtime/stop events for a line within [start, end), ordered by timestamp ascending.

    Each dict: {"line_id": str, "station_id": str, "downtime_reason": str,
    "timestamp": datetime, "downtime_minutes": float}. Derived from OutputLog
    rows in the window where downtime_minutes > 0.

    `line_id` here is the *line_code* (the human-readable string identifier
    used in the CSV contract and by other modules — e.g. Quality's own CSV
    also has a `line_id` column that is this same code), NOT the numeric
    primary key. This is the one function another module (Quality) calls
    directly — keep this signature and return shape stable.
    """
    line = await db.scalar(select(Line).where(Line.tenant_id == tenant_id, Line.line_code == line_id))
    if not line:
        return []

    rows = (
        await db.scalars(
            select(OutputLog)
            .where(
                OutputLog.tenant_id == tenant_id,
                OutputLog.line_id == line.id,
                OutputLog.timestamp >= start,
                OutputLog.timestamp < end,
                OutputLog.downtime_minutes > 0,
            )
            .order_by(OutputLog.timestamp.asc())
        )
    ).all()

    return [
        {
            "line_id": line_id,
            "station_id": r.station_id,
            "downtime_reason": r.downtime_reason,
            "timestamp": r.timestamp,
            "downtime_minutes": r.downtime_minutes,
        }
        for r in rows
    ]


async def summarize_downtime_stops(
    db: AsyncSession, tenant_id: int, line_id: str, start: datetime, end: datetime
) -> list[dict]:
    """Groups discrete downtime rows (each row IS one stop occurrence — see
    get_downtime_events) by station into the PRD's own worked example shape:
    "Station 3, two unplanned stops (34 min) at 11:00-11:40" — a count of
    stops, total minutes, and the time window they span, not just a running
    total. Sorted worst-station-first so the chatbot/dashboard can lead with
    the actual drag on the line.
    """
    events = await get_downtime_events(db, tenant_id, line_id, start, end)

    grouped: dict[str, list[dict]] = {}
    for e in events:
        grouped.setdefault(e["station_id"], []).append(e)

    stops = []
    for station, station_events in grouped.items():
        station_events.sort(key=lambda e: e["timestamp"])
        total_minutes = sum(e["downtime_minutes"] for e in station_events)
        window_start = station_events[0]["timestamp"]
        window_end = max(e["timestamp"] + timedelta(minutes=e["downtime_minutes"]) for e in station_events)
        reasons = sorted({e["downtime_reason"] for e in station_events if e["downtime_reason"]})
        stops.append(
            {
                "station_id": station,
                "stop_count": len(station_events),
                "total_minutes": round(total_minutes, 1),
                "window_start": window_start.strftime("%H:%M"),
                "window_end": window_end.strftime("%H:%M"),
                "reasons": reasons,
            }
        )

    return sorted(stops, key=lambda s: s["total_minutes"], reverse=True)
