from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ChatToolSpec, ModuleSummary, ShiftContribution, register_tool
from app.core.ingestion import CSVSpec, ColumnSpec
from app.core.models_shared import ModuleFreshness
from app.modules.predictive_maintenance.models import Asset, MaintenanceHistory, Recommendation, SensorReading

MODULE_KEY = "predictive_maintenance"


class ServiceError(Exception):
    pass


# ---------------------------------------------------------------------------
# Asset registry CRUD
# ---------------------------------------------------------------------------

async def list_assets(db: AsyncSession, tenant_id: int) -> list[Asset]:
    result = await db.scalars(select(Asset).where(Asset.tenant_id == tenant_id).order_by(Asset.name))
    return list(result)


async def get_asset(db: AsyncSession, tenant_id: int, asset_id: int) -> Asset | None:
    return await db.scalar(select(Asset).where(Asset.tenant_id == tenant_id, Asset.id == asset_id))


async def create_asset(db: AsyncSession, tenant_id: int, payload) -> Asset:
    existing = await db.scalar(
        select(Asset).where(Asset.tenant_id == tenant_id, Asset.asset_code == payload.asset_code)
    )
    if existing:
        raise ServiceError(f"Asset code '{payload.asset_code}' already exists for this tenant")

    asset = Asset(
        tenant_id=tenant_id,
        asset_code=payload.asset_code,
        name=payload.name,
        category=payload.category,
        line_area=payload.line_area,
        criticality=payload.criticality,
        monitored_metrics=payload.monitored_metrics,
        service_intervals=payload.service_intervals,
        install_date=payload.install_date,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def update_asset(db: AsyncSession, tenant_id: int, asset_id: int, payload) -> Asset | None:
    asset = await get_asset(db, tenant_id, asset_id)
    if asset is None:
        return None

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(asset, field, value)

    await db.commit()
    await db.refresh(asset)
    return asset


async def delete_asset(db: AsyncSession, tenant_id: int, asset_id: int) -> bool:
    asset = await get_asset(db, tenant_id, asset_id)
    if asset is None:
        return False
    await db.delete(asset)
    await db.commit()
    return True


async def get_asset_readings(db: AsyncSession, tenant_id: int, asset_id: int, metric: str, days: int) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.scalars(
        select(SensorReading)
        .where(
            SensorReading.tenant_id == tenant_id,
            SensorReading.asset_id == asset_id,
            SensorReading.metric == metric,
            SensorReading.timestamp >= cutoff,
        )
        .order_by(SensorReading.timestamp.asc())
    )
    readings = list(result)

    asset = await get_asset(db, tenant_id, asset_id)
    metric_cfg = (asset.monitored_metrics or {}).get(metric, {}) if asset else {}

    return {
        "asset_id": asset_id,
        "metric": metric,
        "min": metric_cfg.get("min"),
        "max": metric_cfg.get("max"),
        "unit": metric_cfg.get("unit"),
        "readings": [{"timestamp": r.timestamp, "value": r.value, "unit": r.unit} for r in readings],
    }


async def list_maintenance_history(db: AsyncSession, tenant_id: int, asset_id: int) -> list[MaintenanceHistory]:
    # Not explicitly listed in the spec's endpoint table, but needed so the FE
    # can offer a maintenance-history record to link when marking a
    # recommendation "actioned" (POST /recommendations/{id}/action takes a
    # maintenance_history_id — the user has to be able to see the options).
    result = await db.scalars(
        select(MaintenanceHistory)
        .where(MaintenanceHistory.tenant_id == tenant_id, MaintenanceHistory.asset_id == asset_id)
        .order_by(MaintenanceHistory.date.desc())
    )
    return list(result)


async def get_reading(db: AsyncSession, tenant_id: int, asset_id: int, reading_id: int) -> SensorReading | None:
    return await db.scalar(
        select(SensorReading).where(
            SensorReading.tenant_id == tenant_id, SensorReading.asset_id == asset_id, SensorReading.id == reading_id
        )
    )


async def update_reading(db: AsyncSession, tenant_id: int, asset_id: int, reading_id: int, payload) -> SensorReading | None:
    reading = await get_reading(db, tenant_id, asset_id, reading_id)
    if reading is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(reading, field, value)
    await db.commit()
    await db.refresh(reading)
    return reading


async def delete_reading(db: AsyncSession, tenant_id: int, asset_id: int, reading_id: int) -> bool:
    reading = await get_reading(db, tenant_id, asset_id, reading_id)
    if reading is None:
        return False
    await db.delete(reading)
    await db.commit()
    return True


async def get_maintenance_record(db: AsyncSession, tenant_id: int, asset_id: int, record_id: int) -> MaintenanceHistory | None:
    return await db.scalar(
        select(MaintenanceHistory).where(
            MaintenanceHistory.tenant_id == tenant_id,
            MaintenanceHistory.asset_id == asset_id,
            MaintenanceHistory.id == record_id,
        )
    )


async def update_maintenance_record(db: AsyncSession, tenant_id: int, asset_id: int, record_id: int, payload) -> MaintenanceHistory | None:
    record = await get_maintenance_record(db, tenant_id, asset_id, record_id)
    if record is None:
        return None
    data = payload.model_dump(exclude_unset=True, exclude={"event_date"})
    for field, value in data.items():
        setattr(record, field, value)
    if payload.event_date is not None:
        record.date = payload.event_date
    await db.commit()
    await db.refresh(record)
    return record


async def delete_maintenance_record(db: AsyncSession, tenant_id: int, asset_id: int, record_id: int) -> bool:
    record = await get_maintenance_record(db, tenant_id, asset_id, record_id)
    if record is None:
        return False
    await db.delete(record)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# CSV ingestion specs
# ---------------------------------------------------------------------------

async def _asset_code_exists(db: AsyncSession, tenant_id: int, value: str) -> bool:
    row = await db.scalar(select(Asset.id).where(Asset.tenant_id == tenant_id, Asset.asset_code == value))
    return row is not None


async def _check_asset_exists_for_upsert(db: AsyncSession, tenant_id: int, parsed: dict) -> str | None:
    """Non-blocking warning: tells the user this asset_code already exists and will be updated."""
    code = parsed.get("asset_code")
    if not code:
        return None
    existing = await db.scalar(select(Asset.id).where(Asset.tenant_id == tenant_id, Asset.asset_code == code))
    if existing is not None:
        return f"asset_code '{code}' already exists — will be updated on commit"
    return None


ASSET_CSV_SPEC = CSVSpec(
    module=MODULE_KEY,
    columns=[
        ColumnSpec(name="asset_code", dtype="str"),
        ColumnSpec(name="name", dtype="str"),
        ColumnSpec(name="category", dtype="str", required=False),
        ColumnSpec(name="line_area", dtype="str", required=False),
        ColumnSpec(name="criticality", dtype="enum", required=False, enum_values=["low", "med", "high"]),
        ColumnSpec(name="install_date", dtype="datetime", required=False),
    ],
    row_warnings=[_check_asset_exists_for_upsert],
)


async def commit_assets_config(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> tuple[int, int]:
    """Upsert assets from CSV: create new, update existing by asset_code."""
    created = 0
    updated = 0
    for row in valid_rows:
        existing = await db.scalar(
            select(Asset).where(Asset.tenant_id == tenant_id, Asset.asset_code == row["asset_code"])
        )
        if existing is not None:
            existing.name = row["name"]
            existing.category = row.get("category") or ""
            existing.line_area = row.get("line_area") or ""
            existing.criticality = row.get("criticality") or "med"
            if row.get("install_date"):
                dt = row["install_date"]
                existing.install_date = dt.date() if hasattr(dt, "date") else dt
            updated += 1
        else:
            install_date = row.get("install_date")
            if install_date and hasattr(install_date, "date"):
                install_date = install_date.date()
            db.add(
                Asset(
                    tenant_id=tenant_id,
                    asset_code=row["asset_code"],
                    name=row["name"],
                    category=row.get("category") or "",
                    line_area=row.get("line_area") or "",
                    criticality=row.get("criticality") or "med",
                    install_date=install_date,
                )
            )
            created += 1
    await db.commit()
    return created, updated


READINGS_CSV_SPEC = CSVSpec(
    module=MODULE_KEY,
    columns=[
        ColumnSpec(name="asset_id", dtype="str"),
        ColumnSpec(name="timestamp", dtype="datetime"),
        ColumnSpec(name="metric", dtype="str"),
        ColumnSpec(name="value", dtype="float"),
        ColumnSpec(name="unit", dtype="str", required=False),
    ],
    fk_checks={"asset_id": _asset_code_exists},
)

MAINTENANCE_CSV_SPEC = CSVSpec(
    module=MODULE_KEY,
    columns=[
        ColumnSpec(name="asset_id", dtype="str"),
        ColumnSpec(name="date", dtype="datetime"),
        ColumnSpec(name="type", dtype="enum", enum_values=["preventive", "corrective"]),
        ColumnSpec(name="description", dtype="str", required=False),
        ColumnSpec(name="downtime_hours", dtype="float", required=False),
        ColumnSpec(name="parts_replaced", dtype="str", required=False),
        # Optional — same "set the interval when you log the task" idea the
        # quick-add form uses (see quick_log_maintenance in router.py), just
        # available here too so CSV/DB-import bulk history can set it as well,
        # not only a one-off manual entry. Keyed on `description` per row
        # (falls back to "service") since that's the only per-row task label
        # this spec has — a blank/zero value here leaves the asset's existing
        # service_intervals untouched for that task.
        ColumnSpec(name="service_interval_hours", dtype="float", required=False),
    ],
    fk_checks={"asset_id": _asset_code_exists},
)

# One row per (asset, metric) — asset_code ties it to the asset, metric_name
# is arbitrary (vibration, temperature, pressure, current, ...), and min/max/
# unit define what "normal" means for that specific measurement. This is the
# syncable/importable source for Asset.monitored_metrics (a JSONB dict keyed
# by metric name) — the engine's threshold/trend checks already read that
# field directly, so this only adds a tabular way to *populate* it (manual
# form, CSV, or continuous DB sync), not a second copy of the data.
ASSET_METRIC_RANGE_CSV_SPEC = CSVSpec(
    module=MODULE_KEY,
    columns=[
        ColumnSpec(name="asset_code", dtype="str"),
        ColumnSpec(name="metric_name", dtype="str"),
        ColumnSpec(name="min", dtype="float"),
        ColumnSpec(name="max", dtype="float"),
        ColumnSpec(name="unit", dtype="str", required=False),
    ],
    fk_checks={"asset_code": _asset_code_exists},
)


async def _asset_code_map(db: AsyncSession, tenant_id: int) -> dict[str, int]:
    result = await db.execute(select(Asset.asset_code, Asset.id).where(Asset.tenant_id == tenant_id))
    return {code: asset_id for code, asset_id in result.all()}


async def commit_asset_metric_ranges(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> int:
    """Upserts each row into its asset's monitored_metrics — one metric's
    range at a time, so re-syncing a table that only has some assets/metrics
    updates just those, leaving every other metric already configured
    untouched."""
    from app.core.ingestion import touch_freshness

    assets_by_code = {a.asset_code: a for a in await list_assets(db, tenant_id)}
    updated = 0
    for row in valid_rows:
        asset = assets_by_code.get(row["asset_code"])
        if asset is None:
            continue
        metrics = dict(asset.monitored_metrics or {})
        metrics[row["metric_name"]] = {"min": row["min"], "max": row["max"], "unit": row.get("unit") or ""}
        asset.monitored_metrics = metrics  # reassign, not in-place mutate — SQLAlchemy only detects JSON changes this way
        updated += 1
    await db.commit()
    await touch_freshness(db, tenant_id, MODULE_KEY)
    return updated


async def commit_readings(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> int:
    code_map = await _asset_code_map(db, tenant_id)
    count = 0
    for row in valid_rows:
        asset_id = code_map.get(row["asset_id"])
        if asset_id is None:
            continue
        db.add(
            SensorReading(
                tenant_id=tenant_id,
                asset_id=asset_id,
                timestamp=row["timestamp"],
                metric=row["metric"],
                value=row["value"],
                unit=row.get("unit") or "",
            )
        )
        count += 1
    await db.commit()
    return count


async def commit_maintenance_history(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> int:
    # Lazy import, matching load_sample_data's own convention below — engine.py
    # doesn't import this module, so there's no real circularity, but every
    # other cross-reference to engine.py in this file is deliberately deferred
    # the same way.
    from app.modules.predictive_maintenance.engine import capture_failure_signatures

    code_map = await _asset_code_map(db, tenant_id)
    assets_by_id = {a.id: a for a in await list_assets(db, tenant_id)}
    count = 0
    for row in valid_rows:
        asset_id = code_map.get(row["asset_id"])
        if asset_id is None:
            continue
        event_date = row["date"].date() if hasattr(row["date"], "date") else row["date"]
        mh = MaintenanceHistory(
            tenant_id=tenant_id,
            asset_id=asset_id,
            date=event_date,
            type=row["type"],
            description=row.get("description") or "",
            downtime_hours=row.get("downtime_hours") or 0.0,
            parts_replaced=row.get("parts_replaced"),
        )
        db.add(mh)
        count += 1

        # Same "set the interval when you log the task" behavior the manual
        # quick-add form has — applied here too so CSV/DB-import rows carry
        # it just as well as a one-off manual entry does.
        interval_hours = row.get("service_interval_hours")
        if interval_hours:
            asset = assets_by_id.get(asset_id)
            if asset is not None:
                task_key = (row.get("description") or "service").strip() or "service"
                intervals = dict(asset.service_intervals or {})
                intervals[task_key] = {"interval_hours": interval_hours}
                asset.service_intervals = intervals  # reassign, not in-place mutate — SQLAlchemy only detects JSON changes this way

        if row["type"] == "corrective":
            # This is what builds the failure-case library that
            # _check_historical_pattern_match compares future trends
            # against — captured automatically, from ordinary CSV/DB-import/
            # sync commits, not a separate authoring step.
            await db.flush()  # assigns mh.id
            asset = await get_asset(db, tenant_id, asset_id)
            if asset is not None:
                await capture_failure_signatures(db, tenant_id, asset, mh.id, event_date)

    await db.commit()
    return count


# ---------------------------------------------------------------------------
# Recommendation lifecycle
# ---------------------------------------------------------------------------

async def list_recommendations(
    db: AsyncSession, tenant_id: int, status: str | None = None, urgency: str | None = None
) -> list[Recommendation]:
    query = select(Recommendation).where(Recommendation.tenant_id == tenant_id)
    if status:
        query = query.where(Recommendation.status == status)
    if urgency:
        query = query.where(Recommendation.urgency == urgency)
    query = query.order_by(Recommendation.created_at.desc())
    result = await db.scalars(query)
    return list(result)


async def get_recommendation(db: AsyncSession, tenant_id: int, rec_id: int) -> Recommendation | None:
    return await db.scalar(
        select(Recommendation).where(Recommendation.tenant_id == tenant_id, Recommendation.id == rec_id)
    )


async def get_recommendation_stats(db: AsyncSession, tenant_id: int) -> dict:
    """Counts grouped by status + urgency for the §5.7 analytics requirement."""
    all_recs = await list_recommendations(db, tenant_id)

    by_status: dict[str, int] = {"open": 0, "acknowledged": 0, "actioned": 0, "dismissed": 0}
    by_urgency: dict[str, int] = {"high": 0, "med": 0, "low": 0}

    for r in all_recs:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_urgency[r.urgency] = by_urgency.get(r.urgency, 0) + 1

    return {
        "total": len(all_recs),
        "by_status": by_status,
        "by_urgency": by_urgency,
    }


# How far back each granularity looks, and the window length each bucket
# represents — a "day" view showing 5 years of daily bars would be
# unreadable, so the lookback scales down as the bucket gets finer.
_TREND_LOOKBACK_DAYS = {"day": 30, "week": 84, "month": 365, "year": 365 * 5}
_TREND_SQL_TRUNC = {"day": "day", "week": "week", "month": "month", "year": "year"}


async def get_recommendation_trend(
    db: AsyncSession, tenant_id: int, granularity: str = "day", urgency: str | None = None
) -> list[dict]:
    """Issue counts bucketed by period (day/week/month/year) and urgency —
    the dashboard's "Issues" trend chart. Always returns every urgency's
    count per period (so a stacked-by-criticality chart can render directly);
    `urgency` narrows which recommendations are counted at all, for a
    single-criticality view instead of the full breakdown.
    """
    from sqlalchemy import func

    if granularity not in _TREND_SQL_TRUNC:
        granularity = "day"
    lookback_days = _TREND_LOOKBACK_DAYS[granularity]
    window_start = datetime.utcnow() - timedelta(days=lookback_days)

    period = func.date_trunc(_TREND_SQL_TRUNC[granularity], Recommendation.created_at).label("period")
    query = (
        select(period, Recommendation.urgency, func.count().label("count"))
        .where(Recommendation.tenant_id == tenant_id, Recommendation.created_at >= window_start)
    )
    if urgency:
        query = query.where(Recommendation.urgency == urgency)
    query = query.group_by(period, Recommendation.urgency).order_by(period)

    rows = (await db.execute(query)).all()

    buckets: dict[datetime, dict[str, int]] = {}
    for period_value, row_urgency, count in rows:
        bucket = buckets.setdefault(period_value, {"low": 0, "med": 0, "high": 0})
        bucket[row_urgency] = count

    return [
        {"period": p.isoformat(), "low": counts["low"], "med": counts["med"], "high": counts["high"],
         "total": counts["low"] + counts["med"] + counts["high"]}
        for p, counts in sorted(buckets.items())
    ]


# Lifecycle per PRD §5.5: open -> acknowledged -> actioned | dismissed is the
# *typical* path, but this only enforces the one rule that actually matters:
# actioned/dismissed are terminal — once there, no further transition (even
# "back" to acknowledged) is allowed. It deliberately does NOT require
# passing through "acknowledged" first — "open" -> "actioned"/"dismissed"
# directly is allowed too (e.g. a technician who fixes something on sight
# without a separate acknowledge click). Re-requesting the same status the
# recommendation is already in is a harmless no-op rather than an error, so a
# double-click / retried request doesn't surface a confusing failure.
_TERMINAL_STATUSES = ("actioned", "dismissed")


def _ensure_transition_allowed(rec: Recommendation, target: str) -> None:
    if rec.status == target:
        return
    if rec.status in _TERMINAL_STATUSES:
        raise ServiceError(
            f"recommendation is already '{rec.status}' and cannot be changed to '{target}'"
        )


async def acknowledge_recommendation(db: AsyncSession, tenant_id: int, rec_id: int) -> Recommendation | None:
    rec = await get_recommendation(db, tenant_id, rec_id)
    if rec is None:
        return None
    _ensure_transition_allowed(rec, "acknowledged")
    rec.status = "acknowledged"
    await db.commit()
    await db.refresh(rec)
    return rec


async def action_recommendation(
    db: AsyncSession, tenant_id: int, rec_id: int, maintenance_history_id: int
) -> Recommendation | None:
    rec = await get_recommendation(db, tenant_id, rec_id)
    if rec is None:
        return None
    _ensure_transition_allowed(rec, "actioned")
    mh = await db.scalar(
        select(MaintenanceHistory).where(
            MaintenanceHistory.tenant_id == tenant_id, MaintenanceHistory.id == maintenance_history_id
        )
    )
    if mh is None:
        raise ServiceError("maintenance history record not found")
    rec.status = "actioned"
    rec.linked_maintenance_id = maintenance_history_id
    await db.commit()
    await db.refresh(rec)
    await _clear_alert_dedup(db, tenant_id, rec)
    return rec


async def dismiss_recommendation(db: AsyncSession, tenant_id: int, rec_id: int) -> Recommendation | None:
    rec = await get_recommendation(db, tenant_id, rec_id)
    if rec is None:
        return None
    _ensure_transition_allowed(rec, "dismissed")
    rec.status = "dismissed"
    await db.commit()
    await db.refresh(rec)
    await _clear_alert_dedup(db, tenant_id, rec)
    return rec


async def _clear_alert_dedup(db: AsyncSession, tenant_id: int, rec: Recommendation) -> None:
    """A closed recommendation (actioned/dismissed) is no longer "still-open",
    so its alert de-dup entry should reset — a brand-new recurrence of the
    same asset+issue later should alert again like a fresh occurrence,
    matching the PRD's literal "still-open" dedup scoping (§5.6).
    """
    from app.modules.notifications.service import clear_sent_alert

    asset = await get_asset(db, tenant_id, rec.asset_id)
    if asset is not None:
        await clear_sent_alert(db, tenant_id, asset.name, rec.issue)


# ---------------------------------------------------------------------------
# Dashboard / shift-report contracts
# ---------------------------------------------------------------------------

async def get_summary(db: AsyncSession, tenant_id: int) -> ModuleSummary:
    open_recs = await list_recommendations(db, tenant_id, status="open")
    high_open = [r for r in open_recs if r.urgency == "high"]
    med_open = [r for r in open_recs if r.urgency == "med"]

    if high_open:
        status = "critical"
    elif med_open:
        status = "warning"
    else:
        status = "ok"

    if open_recs:
        headline = f"{len(open_recs)} open recommendation{'s' if len(open_recs) != 1 else ''}"
        if high_open:
            headline += f" ({len(high_open)} high)"
    else:
        headline = "All assets nominal"

    asset_count = len(await list_assets(db, tenant_id))

    freshness = await db.scalar(
        select(ModuleFreshness).where(ModuleFreshness.tenant_id == tenant_id, ModuleFreshness.module == MODULE_KEY)
    )
    last_updated_at = freshness.last_updated_at if freshness else None
    cadence_hours = freshness.expected_cadence_hours if freshness else None
    if last_updated_at is None:
        is_stale = True
    else:
        is_stale = (datetime.utcnow() - last_updated_at).total_seconds() / 3600 > (cadence_hours or 24)

    has_data = freshness is not None and freshness.last_updated_at is not None
    alerts = len(open_recs) if has_data else None

    return ModuleSummary(
        module=MODULE_KEY,
        title="Predictive Maintenance",
        status=status,
        headline=headline,
        metrics=[
            {"label": "Open recs", "value": str(len(open_recs))},
            {"label": "Assets", "value": str(asset_count)},
        ],
        last_updated_at=last_updated_at,
        is_stale=is_stale,
        expected_cadence_hours=cadence_hours,
        alerts_count=alerts,
        drilldown_path="/predictive-maintenance",
    )


async def get_shift_contribution(db: AsyncSession, tenant_id: int, start: datetime, end: datetime) -> ShiftContribution:
    result = await db.scalars(
        select(Recommendation).where(
            Recommendation.tenant_id == tenant_id,
            Recommendation.created_at >= start,
            Recommendation.created_at <= end,
        )
    )
    new_recs = list(result)

    high_open = [r for r in await list_recommendations(db, tenant_id, status="open") if r.urgency == "high"]

    # PRD §6.3: after a recommendation is actioned it "appears as a closed
    # item in the shift report" — distinct from open_items (next-shift
    # actions), this reports what got resolved *during* this shift.
    closed_result = await db.scalars(
        select(Recommendation).where(
            Recommendation.tenant_id == tenant_id,
            Recommendation.status == "actioned",
            Recommendation.updated_at >= start,
            Recommendation.updated_at <= end,
        )
    )
    closed_recs = list(closed_result)

    # rec.issue already reads as "<Metric/Task> ... on <Asset name>" (see engine.py),
    # so it's used as-is rather than re-prefixing the asset name a second time.
    open_items = [rec.issue for rec in high_open]

    if new_recs:
        first = new_recs[0]
        summary_text = (
            f"{len(new_recs)} new recommendation{'s' if len(new_recs) != 1 else ''} this shift ({first.issue})."
        )
    else:
        summary_text = "No new maintenance issues this shift."
    if closed_recs:
        summary_text += f" {len(closed_recs)} closed this shift ({', '.join(r.issue for r in closed_recs)})."

    return ShiftContribution(
        module=MODULE_KEY,
        summary_text=summary_text,
        data={
            "new_recommendations": len(new_recs),
            "high_urgency_open": len(high_open),
            "closed_items": [{"issue": r.issue, "asset_id": r.asset_id} for r in closed_recs],
        },
        open_items=open_items,
    )


# ---------------------------------------------------------------------------
# Chat tool
# ---------------------------------------------------------------------------

class AssetStatusArgs(BaseModel):
    asset_code: str


async def _resolve_asset(db: AsyncSession, tenant_id: int, asset_code_or_name: str) -> Asset | None:
    """Callers (chat included) often say the asset's plain name ("Filler
    Motor") rather than its code ("FIL-MTR-01") — resolve against both before
    giving up, same convention as shift_reports' schedule-name lookup.
    """
    exact = await db.scalar(select(Asset).where(Asset.tenant_id == tenant_id, Asset.asset_code == asset_code_or_name))
    if exact is not None:
        return exact

    from app.core.dimension_resolver import resolve

    assets = await list_assets(db, tenant_id)
    by_name = {a.name: a for a in assets}
    result = resolve(asset_code_or_name, list(by_name.keys()))
    if result.matched:
        return by_name[result.matched]
    return None


async def get_asset_status(db: AsyncSession, tenant_id: int, asset_code: str) -> dict:
    asset = await _resolve_asset(db, tenant_id, asset_code)
    if asset is None:
        return {"error": f"No asset found matching '{asset_code}'. Use predictive_maintenance_list_assets to see valid asset codes/names."}

    latest_readings = {}
    for metric in (asset.monitored_metrics or {}).keys():
        reading = await db.scalar(
            select(SensorReading)
            .where(
                SensorReading.tenant_id == tenant_id,
                SensorReading.asset_id == asset.id,
                SensorReading.metric == metric,
            )
            .order_by(SensorReading.timestamp.desc())
            .limit(1)
        )
        if reading:
            latest_readings[metric] = {
                "value": reading.value,
                "unit": reading.unit,
                "timestamp": reading.timestamp.isoformat(),
            }

    open_recs = await db.scalars(
        select(Recommendation).where(
            Recommendation.tenant_id == tenant_id,
            Recommendation.asset_id == asset.id,
            Recommendation.status.in_(("open", "acknowledged")),
        )
    )
    recommendations = [
        {
            "issue": r.issue,
            "evidence": r.evidence,
            "urgency": r.urgency,
            "status": r.status,
            "recommended_action": r.recommended_action,
        }
        for r in open_recs
    ]

    from app.core.freshness import get_freshness

    return {
        "asset_code": asset.asset_code,
        "asset_name": asset.name,
        "criticality": asset.criticality,
        "latest_readings": latest_readings,
        "open_recommendations": recommendations,
        "service_intervals": asset.service_intervals,
        "freshness": await get_freshness(db, tenant_id, MODULE_KEY),
    }


register_tool(
    ChatToolSpec(
        name="predictive_maintenance_asset_status",
        description=(
            "Latest readings, open recommendations, and service-interval status for a given asset. "
            "Accepts either the exact asset code or the asset's plain-language name."
        ),
        args_schema=AssetStatusArgs,
        fn=get_asset_status,
    )
)


class ListAssetsArgs(BaseModel):
    pass


async def list_assets_tool(db: AsyncSession, tenant_id: int) -> dict:
    assets = await list_assets(db, tenant_id)
    return {
        "assets": [
            {"asset_code": a.asset_code, "name": a.name, "category": a.category, "line_area": a.line_area, "criticality": a.criticality}
            for a in assets
        ]
    }


register_tool(
    ChatToolSpec(
        name="predictive_maintenance_list_assets",
        description="Lists every registered asset (code, name, category, line/area, criticality) for this tenant.",
        args_schema=ListAssetsArgs,
        fn=list_assets_tool,
    )
)


class ListRecommendationsArgs(BaseModel):
    status: str | None = None
    urgency: str | None = None


async def list_recommendations_tool(db: AsyncSession, tenant_id: int, status: str | None = None, urgency: str | None = None) -> dict:
    """Plantwide recommendation lookup — distinct from
    predictive_maintenance_asset_status (which is scoped to one named
    asset): use this for "what are the open/high-urgency recommendations
    right now" style questions across every asset.
    """
    recs = await list_recommendations(db, tenant_id, status=status, urgency=urgency)
    asset_name_by_id = {a.id: a.name for a in await list_assets(db, tenant_id)}
    return {
        "recommendations": [
            {
                "asset_name": asset_name_by_id.get(r.asset_id, f"Asset #{r.asset_id}"),
                "issue": r.issue,
                "evidence": r.evidence,
                "recommended_action": r.recommended_action,
                "urgency": r.urgency,
                "estimated_window": r.estimated_window,
                "status": r.status,
            }
            for r in recs
        ]
    }


register_tool(
    ChatToolSpec(
        name="predictive_maintenance_list_recommendations",
        description=(
            "Lists maintenance recommendations across ALL assets for this tenant, optionally filtered by "
            "status (open/acknowledged/actioned/dismissed) and/or urgency (low/med/high). Use this for "
            "plantwide questions like 'what are the open high-urgency recommendations right now' — for a "
            "single named asset's status, use predictive_maintenance_asset_status instead."
        ),
        args_schema=ListRecommendationsArgs,
        fn=list_recommendations_tool,
    )
)


# ---------------------------------------------------------------------------
# Load sample data (BRD §5.1/§2.1 — first-class, drives the <30-min onboarding
# goal). Uses the BRD's own worked examples (CNC-04 vibration trend, Compressor
# A current drift) so the demo matches the doc exactly. Relative timestamps
# (computed from "now" at seed time, not fixed calendar dates) so the trend
# engine always finds a genuinely "recent" spike whenever this is run.
# ---------------------------------------------------------------------------

async def load_sample_data(db: AsyncSession, tenant_id: int, user_id: int) -> dict:
    now = datetime.utcnow()

    existing = await db.scalar(select(Asset).where(Asset.tenant_id == tenant_id, Asset.asset_code == "CNC-04"))
    if existing:
        return {"assets_seeded": [], "readings_seeded": 0, "maintenance_records_seeded": 0, "note": "already seeded"}

    cnc = Asset(
        tenant_id=tenant_id,
        asset_code="CNC-04",
        name="CNC Machine #4",
        category="CNC mill",
        line_area="Line 2",
        criticality="high",
        monitored_metrics={"vibration": {"min": 0, "max": 3.0, "unit": "mm/s"}},
        service_intervals={"lubrication": {"interval_hours": 500}},
        install_date=(now - timedelta(days=1400)).date(),
    )
    compressor = Asset(
        tenant_id=tenant_id,
        asset_code="COMP-A",
        name="Compressor A",
        category="Air compressor",
        line_area="High-Precision Filler",
        criticality="med",
        monitored_metrics={"motor_current": {"min": 0, "max": 12.0, "unit": "A"}},
        service_intervals={"lubrication": {"interval_hours": 500}},
        install_date=(now - timedelta(days=900)).date(),
    )
    db.add_all([cnc, compressor])
    await db.flush()

    readings = []
    # CNC-04 vibration trending 2.1 -> 4.8 mm/s over 9 days — the BRD's own
    # dashboard example (§4.1), so the demo recommendation reads identically.
    vibration_points = [(9, 2.1), (6, 2.8), (3, 3.6), (1, 4.2), (0, 4.8)]
    for days_ago, value in vibration_points:
        readings.append(
            SensorReading(
                tenant_id=tenant_id, asset_id=cnc.id, timestamp=now - timedelta(days=days_ago),
                metric="vibration", value=value, unit="mm/s",
            )
        )
    # Compressor A motor current drifting up ~8% this week — the BRD's own
    # chatbot example (§4.1).
    current_points = [(6, 8.0), (4, 8.2), (2, 8.5), (0, 8.7)]
    for days_ago, value in current_points:
        readings.append(
            SensorReading(
                tenant_id=tenant_id, asset_id=compressor.id, timestamp=now - timedelta(days=days_ago),
                metric="motor_current", value=value, unit="A",
            )
        )
    db.add_all(readings)

    maintenance = [
        MaintenanceHistory(
            tenant_id=tenant_id, asset_id=cnc.id, date=(now - timedelta(days=210)).date(),
            type="preventive", description="Routine lubrication service", downtime_hours=1.5,
            parts_replaced="Bearing grease",
        ),
        MaintenanceHistory(
            tenant_id=tenant_id, asset_id=compressor.id, date=(now - timedelta(days=180)).date(),
            type="preventive", description="Routine lubrication service", downtime_hours=1.0,
            parts_replaced=None,
        ),
    ]
    db.add_all(maintenance)
    await db.commit()

    from app.core.ingestion import touch_freshness

    await touch_freshness(db, tenant_id, MODULE_KEY)

    from app.modules.predictive_maintenance.engine import recompute_all

    await recompute_all(db, tenant_id)

    return {
        "assets_seeded": ["CNC-04", "COMP-A"],
        "readings_seeded": len(readings),
        "maintenance_records_seeded": len(maintenance),
    }
