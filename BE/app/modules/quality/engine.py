"""Defect-rate trend computation and root-cause correlation against
Production's downtime events. See DEV_BRIEF_SELF.md section 5.4.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import InspectionRecord

logger = logging.getLogger(__name__)

RECENT_WINDOW_DAYS = 3
SPIKE_MULTIPLIER = 1.5
SPIKE_MIN_ABS_DELTA = 0.01  # 1 percentage point
# Fraction of the tolerance band (|measured - nominal| / tolerance) at which a
# drift counts as "approaching" the limit — 1.0 would already be at/past it.
DRIFT_APPROACHING_FRACTION = 0.8


def is_spike(recent_total: int, recent_rate: float, baseline_rate: float) -> bool:
    """Shared spike condition, reused by compute_defect_trend and the
    shift-contribution/summary computations so the threshold logic lives in
    exactly one place.
    """
    return (
        recent_total > 0
        and recent_rate > baseline_rate * SPIKE_MULTIPLIER
        and (recent_rate - baseline_rate) >= SPIKE_MIN_ABS_DELTA
    )


async def compute_defect_trend(
    db: AsyncSession,
    tenant_id: int,
    part_id: str,
    characteristic_name: str | None = None,
    line_id: str | None = None,
    station_id: str | None = None,
) -> dict:
    """Defect-rate trend for a part(+characteristic) over the last
    RECENT_WINDOW_DAYS ("recent") vs. all history before that ("baseline").

    A part/characteristic can be inspected on more than one line (a
    Characteristic row is scoped to a single line_id/station_id, but nothing
    stops two Characteristic rows sharing part_id+characteristic_name on
    different lines) — pass line_id/station_id whenever the caller knows
    which line's rate it's asking about, otherwise this blends every line's
    inspections into one rate (BRD §4.5's own example is line-scoped:
    "Line 3 defect rate 4.2%").
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RECENT_WINDOW_DAYS)
    # Timestamps stored are naive (from pandas/CSV) — compare against a naive
    # cutoff to avoid tz-aware/naive comparison errors.
    cutoff_naive = cutoff.replace(tzinfo=None)

    conditions = [InspectionRecord.tenant_id == tenant_id, InspectionRecord.part_id == part_id]
    if characteristic_name:
        conditions.append(InspectionRecord.characteristic_name == characteristic_name)
    if line_id:
        conditions.append(InspectionRecord.line_id == line_id)
    if station_id:
        conditions.append(InspectionRecord.station_id == station_id)

    rows = (
        await db.execute(
            select(
                InspectionRecord.timestamp,
                InspectionRecord.pass_fail,
                InspectionRecord.defect_type,
            ).where(*conditions)
        )
    ).all()

    recent_total = recent_fail = 0
    baseline_total = baseline_fail = 0
    defect_counts: dict[str | None, int] = {}

    for ts, pass_fail, defect_type in rows:
        is_recent = ts >= cutoff_naive
        if is_recent:
            recent_total += 1
            if not pass_fail:
                recent_fail += 1
                defect_counts[defect_type] = defect_counts.get(defect_type, 0) + 1
        else:
            baseline_total += 1
            if not pass_fail:
                baseline_fail += 1

    recent_rate = recent_fail / recent_total if recent_total > 0 else 0.0
    baseline_rate = baseline_fail / baseline_total if baseline_total > 0 else 0.0

    spike = is_spike(recent_total, recent_rate, baseline_rate)

    total_recent_failures = sum(defect_counts.values())
    defect_breakdown = [
        {
            "defect_type": defect_type,
            "count": count,
            "pct_of_failures": (count / total_recent_failures * 100) if total_recent_failures > 0 else 0.0,
        }
        for defect_type, count in sorted(defect_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]

    return {
        "recent_total": recent_total,
        "recent_fail": recent_fail,
        "recent_rate": recent_rate,
        "baseline_total": baseline_total,
        "baseline_fail": baseline_fail,
        "baseline_rate": baseline_rate,
        "is_spike": spike,
        "defect_breakdown": defect_breakdown,
    }


async def compute_tolerance_drift(
    db: AsyncSession,
    tenant_id: int,
    part_id: str,
    characteristic_name: str,
    nominal_value: float,
    tolerance: float,
    line_id: str | None = None,
    station_id: str | None = None,
) -> dict:
    """Is the measured value trending toward (or past) its tolerance limit?
    Per BRD §4.5 ("measurements drifting toward a tolerance limit"), distinct
    from the pass/fail defect-rate trend above. Compares the recent-window
    average deviation from nominal against the baseline-window average
    deviation — a real trend over the reading series, not a single snapshot,
    same explainability standard as the rest of the engine.
    """
    empty = {
        "recent_avg_measured": None,
        "baseline_avg_measured": None,
        "recent_limit_fraction": None,
        "baseline_limit_fraction": None,
        "is_drifting_toward_limit": False,
        "is_approaching_limit": False,
    }
    if tolerance <= 0:
        return empty

    now = datetime.now(timezone.utc)
    cutoff_naive = (now - timedelta(days=RECENT_WINDOW_DAYS)).replace(tzinfo=None)

    conditions = [
        InspectionRecord.tenant_id == tenant_id,
        InspectionRecord.part_id == part_id,
        InspectionRecord.characteristic_name == characteristic_name,
    ]
    if line_id:
        conditions.append(InspectionRecord.line_id == line_id)
    if station_id:
        conditions.append(InspectionRecord.station_id == station_id)

    rows = (
        await db.execute(
            select(InspectionRecord.timestamp, InspectionRecord.measured_value).where(*conditions)
        )
    ).all()
    if not rows:
        return empty

    recent_values = [v for ts, v in rows if ts >= cutoff_naive]
    baseline_values = [v for ts, v in rows if ts < cutoff_naive]

    recent_avg = sum(recent_values) / len(recent_values) if recent_values else None
    baseline_avg = sum(baseline_values) / len(baseline_values) if baseline_values else None

    recent_fraction = abs(recent_avg - nominal_value) / tolerance if recent_avg is not None else None
    baseline_fraction = abs(baseline_avg - nominal_value) / tolerance if baseline_avg is not None else None

    is_drifting = (
        recent_fraction is not None
        and baseline_fraction is not None
        and recent_fraction > baseline_fraction
    )
    is_approaching = recent_fraction is not None and recent_fraction >= DRIFT_APPROACHING_FRACTION

    return {
        "recent_avg_measured": recent_avg,
        "baseline_avg_measured": baseline_avg,
        "recent_limit_fraction": recent_fraction,
        "baseline_limit_fraction": baseline_fraction,
        "is_drifting_toward_limit": is_drifting,
        "is_approaching_limit": is_approaching,
    }


async def get_spike_onset(
    db: AsyncSession,
    tenant_id: int,
    part_id: str,
    characteristic_name: str | None = None,
    line_id: str | None = None,
    station_id: str | None = None,
) -> datetime | None:
    """Timestamp of the earliest failing InspectionRecord in the recent
    (last-RECENT_WINDOW_DAYS) window for this part/characteristic.
    """
    now = datetime.now(timezone.utc)
    cutoff_naive = (now - timedelta(days=RECENT_WINDOW_DAYS)).replace(tzinfo=None)

    conditions = [
        InspectionRecord.tenant_id == tenant_id,
        InspectionRecord.part_id == part_id,
        InspectionRecord.pass_fail == False,  # noqa: E712
        InspectionRecord.timestamp >= cutoff_naive,
    ]
    if characteristic_name:
        conditions.append(InspectionRecord.characteristic_name == characteristic_name)
    if line_id:
        conditions.append(InspectionRecord.line_id == line_id)
    if station_id:
        conditions.append(InspectionRecord.station_id == station_id)

    onset = await db.scalar(
        select(InspectionRecord.timestamp).where(*conditions).order_by(InspectionRecord.timestamp.asc()).limit(1)
    )
    return onset


async def find_likely_cause(
    db: AsyncSession,
    tenant_id: int,
    line_id: str,
    spike_onset: datetime,
    station_id: str | None = None,
) -> str | None:
    """Correlate a defect-rate spike's onset with Production's downtime/
    changeover events on the same line in the 2 hours before onset. Degrades
    gracefully (returns None) if Production's function isn't available yet or
    no events line up — never fabricates a cause.

    When station_id is known (the characteristic is tied to a specific
    station), events at that station are preferred — BRD §4.5's own example
    ties the cause to "the 10:30 Station 2 tooling change," not just any stop
    anywhere on the line. Falls back to any station on the line if nothing
    matches at the given station, rather than returning nothing.
    """
    if not line_id or spike_onset is None:
        return None

    try:
        from app.modules.production.service import get_downtime_events
    except ImportError as exc:
        logger.warning("Production.get_downtime_events not available yet: %s", exc)
        return None

    try:
        events = await get_downtime_events(
            db, tenant_id, line_id, spike_onset - timedelta(hours=2), spike_onset
        )
    except Exception as exc:  # defensive: Production module may be mid-build
        logger.warning("get_downtime_events call failed: %s", exc)
        return None

    if not events:
        return None

    if station_id:
        at_station = [e for e in events if e["station_id"] == station_id]
        if at_station:
            events = at_station

    # Pick the event closest to (but before) spike_onset.
    before = [e for e in events if e["timestamp"] <= spike_onset]
    candidates = before or events
    closest = max(candidates, key=lambda e: e["timestamp"])

    return (
        f"Likely cause: {closest['downtime_reason']} at {closest['station_id']}, "
        f"{closest['timestamp'].strftime('%H:%M')}"
    )
