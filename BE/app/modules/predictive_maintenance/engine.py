"""Transparent, arithmetic-only rule/trend engine for predictive maintenance.
No ML — every recommendation must be explainable via a human-readable
evidence string built directly from the numbers below. See DEV_BRIEF_SELF.md
section 5.1 for the full algorithm this implements.
"""
from datetime import datetime, time, timedelta
from typing import Literal

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.service import trigger_recommendation_alert
from app.modules.predictive_maintenance.models import (
    Asset,
    FailureCaseSignature,
    MaintenanceHistory,
    Recommendation,
    SensorReading,
)

# Similarity thresholds for _check_historical_pattern_match — kept as named
# constants since they're the one place in this "arithmetic-only" engine
# where a judgment call (how close is "close enough") isn't derived from the
# asset's own configured min/max band the way threshold/trend checks are.
_DIRECTION_AGREEMENT_SCORE = 0.6
_MAGNITUDE_BONUS_MAX = 0.4
_METRIC_MATCH_THRESHOLD = 0.7
_MIN_MATCHING_METRICS_FOR_MULTI = 2


def _metric_signature(readings: list[SensorReading]) -> tuple[float, float, float, float] | None:
    """(slope, start_value, end_value, days_span) from readings ordered
    ascending by timestamp. None if there isn't enough data or the time span
    is degenerate (all same timestamp) — same shape of check _check_trend
    already does, factored out so the failure-case capture hook (service.py)
    and _check_historical_pattern_match below can both use it.
    """
    if len(readings) < 3:
        return None
    days_since_first = [(r.timestamp - readings[0].timestamp).total_seconds() / 86400 for r in readings]
    values = [r.value for r in readings]
    if max(days_since_first) - min(days_since_first) <= 0:
        return None
    slope, _intercept = np.polyfit(days_since_first, values, 1)
    return float(slope), values[0], values[-1], days_since_first[-1]


async def capture_failure_signatures(
    db: AsyncSession, tenant_id: int, asset: Asset, maintenance_history_id: int, event_date
) -> None:
    """Called once per corrective MaintenanceHistory row (see service.py's
    commit_maintenance_history) — snapshots every monitored metric's 14-day
    pre-event trend as a FailureCaseSignature, so a *future* similar trend on
    this asset can be matched against a real past case instead of a free-text
    description search. Builds the case library from ordinary usage; no
    manual authoring step.
    """
    monitored_metrics = asset.monitored_metrics or {}
    if not monitored_metrics:
        return

    event_datetime = datetime.combine(event_date, time.min)
    cutoff = event_datetime - timedelta(days=14)

    for metric, cfg in monitored_metrics.items():
        if not isinstance(cfg, dict):
            continue
        unit = cfg.get("unit", "")
        result = await db.scalars(
            select(SensorReading)
            .where(
                SensorReading.tenant_id == tenant_id,
                SensorReading.asset_id == asset.id,
                SensorReading.metric == metric,
                SensorReading.timestamp >= cutoff,
                SensorReading.timestamp <= event_datetime,
            )
            .order_by(SensorReading.timestamp.asc())
        )
        signature = _metric_signature(list(result))
        if signature is None:
            continue
        slope, start_value, end_value, days_span = signature
        db.add(
            FailureCaseSignature(
                tenant_id=tenant_id,
                asset_id=asset.id,
                maintenance_history_id=maintenance_history_id,
                metric=metric,
                slope=slope,
                start_value=start_value,
                end_value=end_value,
                unit=unit,
                days_span=days_span,
            )
        )

async def _upsert_recommendation(
    db: AsyncSession,
    tenant_id: int,
    asset: Asset,
    issue_key: str,
    issue: str,
    evidence: str,
    recommended_action: str,
    urgency: Literal["low", "med", "high"],
    estimated_window: str,
) -> None:
    """Create-or-update a Recommendation for (tenant, asset, issue_key).
    Always attempts an alert on create/update — trigger_recommendation_alert
    itself owns the enabled/threshold/de-dup decision (AlertSetting +
    SentAlert), so every urgency level (not just High) is reachable by a
    tenant-configured threshold.
    """
    existing = await db.scalar(
        select(Recommendation).where(
            Recommendation.tenant_id == tenant_id,
            Recommendation.asset_id == asset.id,
            Recommendation.issue_key == issue_key,
            Recommendation.status.in_(("open", "acknowledged")),
        )
    )

    if existing is None:
        rec = Recommendation(
            tenant_id=tenant_id,
            asset_id=asset.id,
            issue_key=issue_key,
            issue=issue,
            evidence=evidence,
            recommended_action=recommended_action,
            urgency=urgency,
            estimated_window=estimated_window,
            status="open",
        )
        db.add(rec)
        await db.flush()
        # Always attempt an alert, at any urgency — trigger_recommendation_alert
        # itself owns the enabled/threshold/de-dup decision (AlertSetting +
        # SentAlert), so gating on urgency=="high" here would make a
        # tenant-configured threshold below High permanently unreachable.
        await trigger_recommendation_alert(
            db,
            tenant_id,
            asset.name,
            issue,
            evidence,
            recommended_action,
            urgency,
            estimated_window,
            dashboard_link=f"/predictive-maintenance?recommendation_id={rec.id}",
        )
        rec.last_alerted_urgency = urgency
        return

    existing.issue = issue
    existing.evidence = evidence
    existing.recommended_action = recommended_action
    existing.urgency = urgency
    existing.estimated_window = estimated_window

    await trigger_recommendation_alert(
        db,
        tenant_id,
        asset.name,
        issue,
        evidence,
        recommended_action,
        urgency,
        estimated_window,
        dashboard_link=f"/predictive-maintenance?recommendation_id={existing.id}",
    )
    existing.last_alerted_urgency = urgency


async def _check_threshold(db: AsyncSession, tenant_id: int, asset: Asset, metric: str, mn: float, mx: float, unit: str) -> None:
    latest = await db.scalar(
        select(SensorReading)
        .where(
            SensorReading.tenant_id == tenant_id,
            SensorReading.asset_id == asset.id,
            SensorReading.metric == metric,
        )
        .order_by(SensorReading.timestamp.desc())
        .limit(1)
    )
    if latest is None:
        return
    if mn <= latest.value <= mx:
        return

    range_width = (mx - mn) if (mx - mn) > 0 else 1.0
    breach_amount = (mn - latest.value) if latest.value < mn else (latest.value - mx)
    relative_breach = breach_amount / range_width
    # Three-tier split by how far outside the calibrated normal range the
    # latest reading sits — a breach isn't automatically an emergency just
    # because it's a breach; only a large one is. A hairline overshoot is
    # worth a routine look, not an "immediate" alert.
    if relative_breach > 0.2:
        urgency = "high"
        action = f"Inspect {metric} on {asset.name} immediately"
        window = "immediate"
    elif relative_breach > 0.05:
        urgency = "med"
        action = f"Inspect {metric} on {asset.name} soon"
        window = "soon"
    else:
        urgency = "low"
        action = f"Keep an eye on {metric} on {asset.name} — just outside range"
        window = "routine"

    issue_key = f"{metric}:threshold"
    issue = f"{metric.capitalize()} threshold breach"
    evidence = f"Latest {metric} reading {latest.value:.1f} {unit}, outside normal range {mn}–{mx} {unit}"

    await _upsert_recommendation(db, tenant_id, asset, issue_key, issue, evidence, action, urgency, window)


async def _check_trend(db: AsyncSession, tenant_id: int, asset: Asset, metric: str, mn: float, mx: float, unit: str) -> None:
    cutoff = datetime.utcnow() - timedelta(days=14)
    result = await db.scalars(
        select(SensorReading)
        .where(
            SensorReading.tenant_id == tenant_id,
            SensorReading.asset_id == asset.id,
            SensorReading.metric == metric,
            SensorReading.timestamp >= cutoff,
        )
        .order_by(SensorReading.timestamp.asc())
    )
    readings = list(result)
    if len(readings) < 3:
        return

    days_since_first = [(r.timestamp - readings[0].timestamp).total_seconds() / 86400 for r in readings]
    values = [r.value for r in readings]

    # Guard against a degenerate/zero time-span series (all same timestamp).
    if max(days_since_first) - min(days_since_first) <= 0:
        return

    slope, intercept = np.polyfit(days_since_first, values, 1)
    last_x = days_since_first[-1]
    projected = slope * (last_x + 14) + intercept

    fires = False
    bound = None
    if slope > 0 and projected > mx:
        fires = True
        bound = mx
    elif slope < 0 and projected < mn:
        fires = True
        bound = mn

    if not fires or slope == 0:
        return

    x_breach = (bound - intercept) / slope
    days_to_breach = x_breach - last_x
    days_to_breach = max(0.0, min(14.0, days_to_breach))

    # Three-tier split by how soon the 14-day-out projection actually
    # crosses the limit — a trend that won't breach for another week and a
    # half is worth watching, not an "immediate" call to action.
    if days_to_breach <= 5:
        urgency = "high"
    elif days_to_breach <= 10:
        urgency = "med"
    else:
        urgency = "low"
    issue_key = f"{metric}:trend"
    issue = f"{metric.capitalize()} trending toward limit"
    normal_desc = f"≤ {mx} {unit}" if slope > 0 else f"≥ {mn} {unit}"
    evidence = (
        f"{metric} {readings[0].value:.1f} → {readings[-1].value:.1f} {unit} over {last_x:.0f} days "
        f"(normal {normal_desc})"
    )
    # Rounding days_to_breach to whole days for display would otherwise let a
    # sub-day projection (e.g. 0.3 days out) print as the nonsensical
    # "within 0 days" — say "immediately" instead, matching how
    # _check_threshold already phrases an already-breached metric.
    if days_to_breach < 1:
        action = f"Schedule {metric} inspection immediately"
        window = "immediate"
    else:
        action = f"Schedule {metric} inspection within {days_to_breach:.0f} days"
        window = f"~{days_to_breach:.0f} days"

    await _upsert_recommendation(db, tenant_id, asset, issue_key, issue, evidence, action, urgency, window)


async def _check_service_interval(db: AsyncSession, tenant_id: int, asset: Asset, task: str, interval_hours: float) -> None:
    # Per-task tracking: reference point is the most recent preventive
    # maintenance row whose description mentions this task (case-insensitive
    # substring match). If none is found, fall back to install_date — v1
    # simplification documented in the module's final report.
    latest_service = await db.scalar(
        select(MaintenanceHistory)
        .where(
            MaintenanceHistory.tenant_id == tenant_id,
            MaintenanceHistory.asset_id == asset.id,
            MaintenanceHistory.type == "preventive",
            MaintenanceHistory.description.ilike(f"%{task}%"),
        )
        .order_by(MaintenanceHistory.date.desc())
        .limit(1)
    )

    if latest_service is not None:
        reference_date = latest_service.date
    elif asset.install_date is not None:
        reference_date = asset.install_date
    else:
        return  # no reference point at all — can't evaluate this rule yet

    reference_datetime = datetime.combine(reference_date, time.min)
    now = datetime.utcnow()
    hours_since = (now - reference_datetime).total_seconds() / 3600

    downtime_result = await db.scalars(
        select(MaintenanceHistory.downtime_hours).where(
            MaintenanceHistory.tenant_id == tenant_id,
            MaintenanceHistory.asset_id == asset.id,
            MaintenanceHistory.date > reference_date,
        )
    )
    total_downtime_hours = sum(downtime_result.all() or [0.0])

    running_hours_estimate = max(0.0, hours_since - total_downtime_hours)

    issue_key = f"{task}:interval"
    issue = f"{task.capitalize()} interval due"
    evidence = f"{running_hours_estimate:.0f} running-hours since last {task}, interval is {interval_hours}"

    if running_hours_estimate >= interval_hours:
        urgency = "high"
        action = f"Perform {task} — overdue"
        window = "overdue now"
    elif running_hours_estimate >= 0.9 * interval_hours:
        urgency = "med"
        action = f"Schedule {task} soon — approaching interval"
        window = f"~{(interval_hours - running_hours_estimate):.0f} hours remaining"
    elif running_hours_estimate >= 0.75 * interval_hours:
        urgency = "low"
        action = f"Plan for {task} — interval approaching"
        window = f"~{(interval_hours - running_hours_estimate):.0f} hours remaining"
    else:
        return  # rule doesn't fire

    await _upsert_recommendation(db, tenant_id, asset, issue_key, issue, evidence, action, urgency, window)


async def _check_historical_pattern_match(db: AsyncSession, tenant_id: int, asset: Asset) -> None:
    """Historical case-based pattern matching, jointly across every monitored
    metric — answers "why did it stop" (linked to the actual past
    MaintenanceHistory case), "before it stops" (fires on a live trend, not a
    threshold breach), and "the reason" (evidence names real numbers for each
    contributing metric). Still arithmetic/explainable, no ML: a joint
    similarity score built from per-metric direction agreement + normalized
    magnitude closeness against FailureCaseSignature rows captured by
    capture_failure_signatures above.

    Called once per asset (not once per metric like the checks above) since
    the whole point is comparing several metrics' current trends jointly
    against the same past case.
    """
    monitored_metrics = asset.monitored_metrics or {}
    valid_metrics = {
        m: cfg for m, cfg in monitored_metrics.items() if isinstance(cfg, dict) and "min" in cfg and "max" in cfg
    }
    if not valid_metrics:
        return

    cutoff = datetime.utcnow() - timedelta(days=14)
    current_signatures: dict[str, tuple[float, float, float, float]] = {}
    for metric in valid_metrics:
        result = await db.scalars(
            select(SensorReading)
            .where(
                SensorReading.tenant_id == tenant_id,
                SensorReading.asset_id == asset.id,
                SensorReading.metric == metric,
                SensorReading.timestamp >= cutoff,
            )
            .order_by(SensorReading.timestamp.asc())
        )
        signature = _metric_signature(list(result))
        if signature is not None and abs(signature[0]) >= 0.01:
            current_signatures[metric] = signature

    if not current_signatures:
        return

    case_rows = list(
        await db.scalars(
            select(FailureCaseSignature).where(
                FailureCaseSignature.tenant_id == tenant_id,
                FailureCaseSignature.asset_id == asset.id,
            )
        )
    )
    if not case_rows:
        return

    cases_by_event: dict[int, list[FailureCaseSignature]] = {}
    for row in case_rows:
        cases_by_event.setdefault(row.maintenance_history_id, []).append(row)

    best_score = 0.0
    best_event_id: int | None = None
    best_contributing: list[tuple[str, float, float]] = []  # metric, current_slope, case_slope

    for event_id, sigs in cases_by_event.items():
        contributing: list[tuple[str, float, float]] = []
        for sig in sigs:
            current = current_signatures.get(sig.metric)
            if current is None:
                continue
            current_slope = current[0]

            cfg = valid_metrics.get(sig.metric)
            range_width = float(cfg["max"]) - float(cfg["min"]) if cfg else 0.0
            if range_width <= 0:
                range_width = max(abs(sig.end_value - sig.start_value), abs(current[2] - current[1]), 1.0)

            current_norm = current_slope / range_width
            case_norm = sig.slope / range_width
            if (current_norm > 0) != (case_norm > 0):
                continue  # opposite direction — no match on this metric

            denom = max(abs(current_norm), abs(case_norm), 1e-6)
            relative_diff = min(1.0, abs(current_norm - case_norm) / denom)
            score = _DIRECTION_AGREEMENT_SCORE + _MAGNITUDE_BONUS_MAX * (1 - relative_diff)

            if score >= _METRIC_MATCH_THRESHOLD:
                contributing.append((sig.metric, current_slope, sig.slope))

        if not contributing:
            continue
        # Assets monitoring more than one metric need corroboration from at
        # least two before firing — a single noisy metric shouldn't be enough
        # to claim a joint pattern match. An asset configured with only one
        # monitored metric (e.g. the CNC-04 demo) can still match on that one.
        if len(valid_metrics) > 1 and len(contributing) < _MIN_MATCHING_METRICS_FOR_MULTI:
            continue

        # More contributing metrics -> a stronger case; simplest total order
        # for picking among several matching past events. Deliberately a
        # fresh variable rather than reusing the inner loop's per-metric
        # `score` name, even though that loop has already finished by here.
        event_score = float(len(contributing))
        if event_score > best_score:
            best_score = event_score
            best_event_id = event_id
            best_contributing = contributing

    if best_event_id is None:
        return

    case_event = await db.scalar(select(MaintenanceHistory).where(MaintenanceHistory.id == best_event_id))
    if case_event is None:
        return

    metric_lines = []
    for metric, current_slope, case_slope in best_contributing:
        current = current_signatures[metric]
        unit = next((s.unit for s in cases_by_event[best_event_id] if s.metric == metric), "")
        direction = "rising" if current_slope > 0 else "falling"
        metric_lines.append(
            f"{metric} {direction} {current[1]:.1f} → {current[2]:.1f} {unit} over {current[3]:.0f} days "
            f"(prior event showed the same {direction} trend, {case_slope:+.2f} {unit}/day)"
        )

    metrics_named = ", ".join(m for m, *_ in best_contributing)
    fix_note = case_event.parts_replaced or case_event.description or "no fix recorded for that event"

    issue_key = f"pattern:mh{best_event_id}"
    issue = "Pattern matches prior failure"
    evidence = (
        "; ".join(metric_lines)
        + f". Matches the corrective event on {case_event.date} ({case_event.description or 'no description recorded'})."
    )
    action = f"Investigate {metrics_named} on {asset.name} — same pattern preceded a past failure. Last time, the fix was: {fix_note}."
    window = "schedule soon"

    await _upsert_recommendation(db, tenant_id, asset, issue_key, issue, evidence, action, "med", window)


async def recompute_asset(db: AsyncSession, tenant_id: int, asset: Asset) -> None:
    monitored_metrics = asset.monitored_metrics or {}
    for metric, cfg in monitored_metrics.items():
        if not isinstance(cfg, dict) or "min" not in cfg or "max" not in cfg:
            continue
        mn = float(cfg["min"])
        mx = float(cfg["max"])
        unit = cfg.get("unit", "")
        await _check_threshold(db, tenant_id, asset, metric, mn, mx, unit)
        await _check_trend(db, tenant_id, asset, metric, mn, mx, unit)

    # Once per asset, not once per metric — this check compares several
    # metrics' current trends jointly against the same past failure case.
    await _check_historical_pattern_match(db, tenant_id, asset)

    service_intervals = asset.service_intervals or {}
    for task, cfg in service_intervals.items():
        if not isinstance(cfg, dict) or "interval_hours" not in cfg:
            continue
        await _check_service_interval(db, tenant_id, asset, task, float(cfg["interval_hours"]))

    await db.commit()


async def recompute_all(db: AsyncSession, tenant_id: int) -> None:
    assets = await db.scalars(select(Asset).where(Asset.tenant_id == tenant_id))
    for asset in assets:
        await recompute_asset(db, tenant_id, asset)
