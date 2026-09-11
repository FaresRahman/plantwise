"""Characteristic config CRUD, CSV validate/commit for inspection records
(via app.core.ingestion), defect-rate trend vs baseline, and root-cause
correlation against Production's downtime events. See DEV_BRIEF_SELF.md
section 5.4.

CSV `pass_fail` convention: the column must contain the literal string
"pass" or "fail" (case-sensitive, per app.core.ingestion's enum coercion).
It's converted to a real bool at commit time.
"""
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ChatToolSpec, ModuleSummary, ShiftContribution, register_tool
from app.core.freshness import get_freshness
from app.core.ingestion import ColumnSpec, CSVSpec
from app.core.models_shared import ModuleFreshness
from app.modules.quality import engine
from app.modules.quality.models import Characteristic, InspectionRecord, QualityHold
from app.modules.quality.schemas import CharacteristicIn, QualityHoldIn


class ServiceError(Exception):
    """Raised for invalid quality-hold operations (e.g. releasing an already-
    released hold) — router turns this into a 400.
    """


async def _part_id_exists(db: AsyncSession, tenant_id: int, value: str) -> bool:
    return (
        await db.scalar(
            select(Characteristic).where(Characteristic.tenant_id == tenant_id, Characteristic.part_id == value)
        )
    ) is not None


async def _line_id_exists(db: AsyncSession, tenant_id: int, value: str) -> bool:
    # Cross-module read of Production's own existence check, same pattern as
    # the root-cause correlation below — not a duplicated query.
    from app.modules.production.service import line_code_exists

    return await line_code_exists(db, tenant_id, value)


INSPECTION_RECORD_CSV_SPEC = CSVSpec(
    module="quality",
    columns=[
        ColumnSpec(name="part_id", dtype="str", required=True),
        ColumnSpec(name="timestamp", dtype="datetime", required=True),
        ColumnSpec(name="characteristic", dtype="str", required=True),
        ColumnSpec(name="measured_value", dtype="float", required=True),
        ColumnSpec(name="pass_fail", dtype="enum", required=True, enum_values=["pass", "fail"]),
        ColumnSpec(name="defect_type", dtype="str", required=False),
        ColumnSpec(name="line_id", dtype="str", required=True),
        ColumnSpec(name="station_id", dtype="str", required=False),
        ColumnSpec(name="inspector", dtype="str", required=False),
    ],
    fk_checks={"part_id": _part_id_exists, "line_id": _line_id_exists},
)

INSPECTION_RECORD_CSV_HEADER = (
    "part_id,timestamp,characteristic,measured_value,pass_fail,defect_type,line_id,station_id,inspector"
)


# ---------------------------------------------------------------------------
# Characteristic config CRUD
# ---------------------------------------------------------------------------

async def list_characteristics(db: AsyncSession, tenant_id: int) -> list[Characteristic]:
    result = await db.execute(
        select(Characteristic)
        .where(Characteristic.tenant_id == tenant_id)
        .order_by(Characteristic.part_id, Characteristic.characteristic_name)
    )
    return list(result.scalars().all())


async def get_characteristic(db: AsyncSession, tenant_id: int, characteristic_id: int) -> Characteristic | None:
    return await db.scalar(
        select(Characteristic).where(
            Characteristic.id == characteristic_id, Characteristic.tenant_id == tenant_id
        )
    )


async def create_characteristic(db: AsyncSession, tenant_id: int, payload: CharacteristicIn) -> Characteristic:
    char = Characteristic(tenant_id=tenant_id, **payload.model_dump())
    db.add(char)
    await db.commit()
    await db.refresh(char)
    return char


async def update_characteristic(
    db: AsyncSession, tenant_id: int, characteristic_id: int, payload: CharacteristicIn
) -> Characteristic | None:
    char = await get_characteristic(db, tenant_id, characteristic_id)
    if char is None:
        return None
    for key, value in payload.model_dump().items():
        setattr(char, key, value)
    await db.commit()
    await db.refresh(char)
    return char


async def delete_characteristic(db: AsyncSession, tenant_id: int, characteristic_id: int) -> bool:
    char = await get_characteristic(db, tenant_id, characteristic_id)
    if char is None:
        return False
    await db.delete(char)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Characteristic config CSV
# ---------------------------------------------------------------------------

async def _check_characteristic_exists_for_upsert(db, tenant_id, parsed):
    """Non-blocking warning for duplicate (part_id, characteristic_name)."""
    part_id = parsed.get("part_id")
    name = parsed.get("characteristic_name")
    if not part_id or not name:
        return None
    existing = await db.scalar(
        select(Characteristic).where(
            Characteristic.tenant_id == tenant_id,
            Characteristic.part_id == part_id,
            Characteristic.characteristic_name == name,
        )
    )
    if existing is not None:
        return f"characteristic '{part_id}/{name}' already exists — will be updated on commit"
    return None


def _parse_semicolon_list(value):
    if not value or not str(value).strip():
        return []
    return [s.strip() for s in str(value).split(";") if s.strip()]


CHARACTERISTIC_CSV_SPEC = CSVSpec(
    module="quality",
    columns=[
        ColumnSpec(name="part_id", dtype="str"),
        ColumnSpec(name="characteristic_name", dtype="str"),
        ColumnSpec(name="nominal_value", dtype="float"),
        ColumnSpec(name="tolerance", dtype="float"),
        ColumnSpec(name="inspection_type", dtype="str", required=False),
        ColumnSpec(name="line_id", dtype="str", required=False),
        ColumnSpec(name="station_id", dtype="str", required=False),
        ColumnSpec(name="defect_categories", dtype="str", required=False),
    ],
    row_warnings=[_check_characteristic_exists_for_upsert],
)


async def commit_characteristics_config(db, tenant_id, valid_rows):
    """Upsert characteristics from CSV by (part_id, characteristic_name)."""
    created = 0
    updated = 0
    for row in valid_rows:
        existing = await db.scalar(
            select(Characteristic).where(
                Characteristic.tenant_id == tenant_id,
                Characteristic.part_id == row["part_id"],
                Characteristic.characteristic_name == row["characteristic_name"],
            )
        )
        if existing is not None:
            existing.nominal_value = row["nominal_value"]
            existing.tolerance = row["tolerance"]
            existing.inspection_type = row.get("inspection_type") or ""
            existing.line_id = row.get("line_id") or ""
            existing.station_id = row.get("station_id") or ""
            existing.defect_categories = _parse_semicolon_list(row.get("defect_categories"))
            updated += 1
        else:
            db.add(Characteristic(
                tenant_id=tenant_id,
                part_id=row["part_id"],
                characteristic_name=row["characteristic_name"],
                nominal_value=row["nominal_value"],
                tolerance=row["tolerance"],
                inspection_type=row.get("inspection_type") or "",
                line_id=row.get("line_id") or "",
                station_id=row.get("station_id") or "",
                defect_categories=_parse_semicolon_list(row.get("defect_categories")),
            ))
            created += 1
    await db.commit()
    return created, updated


# ---------------------------------------------------------------------------
# CSV commit
# ---------------------------------------------------------------------------

async def commit_inspection_rows(
    db: AsyncSession, tenant_id: int, valid_rows: list[dict]
) -> tuple[int, set[tuple[str, str, str]]]:
    """Insert valid inspection-record rows. Returns (count committed, set of
    (part_id, characteristic_name, line_id) touched) so the caller can check
    those characteristics for a fresh spike afterward.
    """
    committed = 0
    touched: set[tuple[str, str, str]] = set()
    for row in valid_rows:
        pass_fail_bool = str(row["pass_fail"]).strip().lower() == "pass"
        record = InspectionRecord(
            tenant_id=tenant_id,
            part_id=row["part_id"],
            timestamp=row["timestamp"],
            characteristic_name=row["characteristic"],
            measured_value=row["measured_value"],
            pass_fail=pass_fail_bool,
            defect_type=row.get("defect_type"),
            line_id=row.get("line_id") or "",
            station_id=row.get("station_id") or "",
            inspector=row.get("inspector") or "",
        )
        db.add(record)
        committed += 1
        touched.add((row["part_id"], row["characteristic"], row.get("line_id") or ""))
    await db.commit()
    return committed, touched


async def check_and_alert_spikes(db: AsyncSession, tenant_id: int, touched: set[tuple[str, str, str]]) -> None:
    """After a CSV commit, re-check each touched (part_id, characteristic,
    line_id) for a fresh defect-rate spike or a tolerance-drift approach and
    fire a generic alert if so.
    """
    from app.modules.notifications.service import clear_generic_alert, trigger_generic_alert

    for part_id, characteristic_name, line_id in touched:
        char = await db.scalar(
            select(Characteristic).where(
                Characteristic.tenant_id == tenant_id,
                Characteristic.part_id == part_id,
                Characteristic.characteristic_name == characteristic_name,
            )
        )
        station_id = char.station_id if char else None

        trend = await engine.compute_defect_trend(
            db, tenant_id, part_id, characteristic_name, line_id=line_id or None, station_id=station_id
        )
        spike_title = f"Defect rate spike: {part_id}/{characteristic_name}"
        if trend["is_spike"]:
            await trigger_generic_alert(
                db,
                tenant_id,
                "quality",
                title=spike_title,
                message=(
                    f"Recent defect rate {trend['recent_rate'] * 100:.1f}% vs baseline "
                    f"{trend['baseline_rate'] * 100:.1f}% on line {line_id or 'unknown'}."
                ),
                dashboard_link="/quality",
            )
        else:
            # Rate back to normal — clear so a future recurrence alerts
            # again instead of being suppressed by the earlier SentAlert row.
            await clear_generic_alert(db, tenant_id, "quality", spike_title)

        if char is None:
            continue
        drift = await engine.compute_tolerance_drift(
            db, tenant_id, part_id, characteristic_name, char.nominal_value, char.tolerance,
            line_id=line_id or None, station_id=station_id,
        )
        drift_title = f"Measurement drifting toward tolerance limit: {part_id}/{characteristic_name}"
        if drift["is_approaching_limit"]:
            await trigger_generic_alert(
                db,
                tenant_id,
                "quality",
                title=drift_title,
                message=(
                    f"Recent average {drift['recent_avg_measured']:.3f} is "
                    f"{drift['recent_limit_fraction'] * 100:.0f}% of the way to the tolerance limit "
                    f"(nominal {char.nominal_value} ± {char.tolerance})."
                ),
                dashboard_link="/quality",
            )
        else:
            await clear_generic_alert(db, tenant_id, "quality", drift_title)


# ---------------------------------------------------------------------------
# Quality holds (lot/batch quarantine)
# ---------------------------------------------------------------------------

async def list_holds(db: AsyncSession, tenant_id: int, status: str | None = None) -> list[QualityHold]:
    query = select(QualityHold).where(QualityHold.tenant_id == tenant_id)
    if status:
        query = query.where(QualityHold.status == status)
    query = query.order_by(QualityHold.created_at.desc())
    return list((await db.scalars(query)).all())


async def get_hold(db: AsyncSession, tenant_id: int, hold_id: int) -> QualityHold | None:
    return await db.scalar(select(QualityHold).where(QualityHold.tenant_id == tenant_id, QualityHold.id == hold_id))


async def create_hold(db: AsyncSession, tenant_id: int, user_id: int, payload: QualityHoldIn) -> QualityHold:
    hold = QualityHold(tenant_id=tenant_id, created_by=user_id, status="open", **payload.model_dump())
    db.add(hold)
    await db.commit()
    await db.refresh(hold)
    return hold


async def release_hold(db: AsyncSession, tenant_id: int, user_id: int, hold_id: int, release_note: str) -> QualityHold | None:
    if not release_note.strip():
        # A hold needs a reason to open (QualityHoldIn.reason) — it needs one
        # to close too, or a lot could be cleared to ship with no record of
        # why it was safe.
        raise ServiceError("release_note is required")
    hold = await get_hold(db, tenant_id, hold_id)
    if hold is None:
        return None
    if hold.status == "released":
        raise ServiceError(f"hold {hold_id} is already released")
    hold.status = "released"
    hold.released_at = datetime.utcnow()
    hold.released_by = user_id
    hold.release_note = release_note.strip()
    await db.commit()
    await db.refresh(hold)
    return hold


# ---------------------------------------------------------------------------
# Trend + root cause (used by the endpoint, dashboard, chat tool)
# ---------------------------------------------------------------------------

async def get_characteristic_trend(db: AsyncSession, tenant_id: int, characteristic: Characteristic) -> dict:
    line_id = characteristic.line_id or None
    station_id = characteristic.station_id or None
    trend = await engine.compute_defect_trend(
        db, tenant_id, characteristic.part_id, characteristic.characteristic_name,
        line_id=line_id, station_id=station_id,
    )
    root_cause = None
    if trend["is_spike"]:
        onset = await engine.get_spike_onset(
            db, tenant_id, characteristic.part_id, characteristic.characteristic_name,
            line_id=line_id, station_id=station_id,
        )
        if onset is not None:
            root_cause = await engine.find_likely_cause(
                db, tenant_id, characteristic.line_id, onset, station_id=station_id
            )
    drift = await engine.compute_tolerance_drift(
        db,
        tenant_id,
        characteristic.part_id,
        characteristic.characteristic_name,
        characteristic.nominal_value,
        characteristic.tolerance,
        line_id=line_id,
        station_id=station_id,
    )
    return {**trend, "root_cause": root_cause, "tolerance_drift": drift}


async def get_recent_measurements(
    db: AsyncSession, tenant_id: int, characteristic: Characteristic, days: int = 30
) -> list[dict]:
    """Raw measured values over time for one characteristic — the "based on
    the values" trend chart, distinct from get_characteristic_trend's
    pass/fail *rate* comparison. Plotted against nominal +/- tolerance so a
    reading drifting toward the limit is visible before it actually fails.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = await db.scalars(
        select(InspectionRecord)
        .where(
            InspectionRecord.tenant_id == tenant_id,
            InspectionRecord.part_id == characteristic.part_id,
            InspectionRecord.characteristic_name == characteristic.characteristic_name,
            InspectionRecord.timestamp >= cutoff,
        )
        .order_by(InspectionRecord.timestamp.asc())
    )
    return [
        {"timestamp": r.timestamp, "measured_value": r.measured_value, "pass_fail": r.pass_fail}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Dashboard contract
# ---------------------------------------------------------------------------

def _is_stale(freshness: ModuleFreshness | None) -> bool:
    if freshness is None:
        return False
    age = datetime.utcnow() - freshness.last_updated_at
    return age > timedelta(hours=freshness.expected_cadence_hours)


async def get_summary(db: AsyncSession, tenant_id: int) -> ModuleSummary:
    characteristics = await list_characteristics(db, tenant_id)
    freshness = await db.scalar(
        select(ModuleFreshness).where(ModuleFreshness.tenant_id == tenant_id, ModuleFreshness.module == "quality")
    )

    spiking: list[tuple[Characteristic, dict]] = []
    drifting: list[Characteristic] = []
    any_critical = False
    for char in characteristics:
        line_id = char.line_id or None
        station_id = char.station_id or None
        trend = await engine.compute_defect_trend(
            db, tenant_id, char.part_id, char.characteristic_name, line_id=line_id, station_id=station_id
        )
        if trend["is_spike"]:
            spiking.append((char, trend))
            if trend["baseline_rate"] > 0 and trend["recent_rate"] > trend["baseline_rate"] * 2:
                any_critical = True
            elif trend["baseline_rate"] == 0 and trend["recent_rate"] > 0:
                any_critical = True

        drift = await engine.compute_tolerance_drift(
            db, tenant_id, char.part_id, char.characteristic_name, char.nominal_value, char.tolerance,
            line_id=line_id, station_id=station_id,
        )
        if drift["is_approaching_limit"]:
            drifting.append(char)

    alerts_count = len(spiking) + len(drifting)
    if alerts_count == 0:
        status = "ok"
        headline = "Quality within normal range"
    elif spiking:
        status = "critical" if any_critical else "warning"
        char, trend = spiking[0]
        label = char.line_id or char.part_id
        headline = (
            f"{label} defect rate {trend['recent_rate'] * 100:.1f}% vs "
            f"{trend['baseline_rate'] * 100:.1f}% baseline"
        )
    else:
        status = "warning"
        char = drifting[0]
        headline = f"{char.part_id}/{char.characteristic_name} drifting toward its tolerance limit"

    alerts_count_val = alerts_count if freshness is not None and freshness.last_updated_at is not None else None

    return ModuleSummary(
        module="quality",
        title="Quality",
        status=status,
        headline=headline,
        metrics=[
            {"label": "Spikes", "value": str(len(spiking))},
            {"label": "Drifting", "value": str(len(drifting))},
            {"label": "Characteristics", "value": str(len(characteristics))},
        ],
        last_updated_at=freshness.last_updated_at if freshness else None,
        is_stale=_is_stale(freshness),
        expected_cadence_hours=freshness.expected_cadence_hours if freshness else None,
        alerts_count=alerts_count_val,
        drilldown_path="/quality",
    )


async def get_shift_contribution(
    db: AsyncSession, tenant_id: int, start: datetime, end: datetime
) -> ShiftContribution:
    start_naive = start.replace(tzinfo=None) if start.tzinfo else start
    end_naive = end.replace(tzinfo=None) if end.tzinfo else end

    rows = (
        await db.execute(
            select(
                InspectionRecord.part_id,
                InspectionRecord.characteristic_name,
                InspectionRecord.line_id,
                InspectionRecord.pass_fail,
                InspectionRecord.timestamp,
            ).where(InspectionRecord.tenant_id == tenant_id, InspectionRecord.timestamp < end_naive)
        )
    ).all()

    shift_total = shift_fail = 0
    baseline_total = baseline_fail = 0
    per_char: dict[tuple[str, str], dict] = {}

    for part_id, characteristic_name, line_id, pass_fail, ts in rows:
        key = (part_id, characteristic_name)
        entry = per_char.setdefault(
            key,
            {
                "part_id": part_id,
                "characteristic_name": characteristic_name,
                "line_id": line_id,
                "shift_total": 0,
                "shift_fail": 0,
                "baseline_total": 0,
                "baseline_fail": 0,
            },
        )
        if ts >= start_naive:
            shift_total += 1
            entry["shift_total"] += 1
            if not pass_fail:
                shift_fail += 1
                entry["shift_fail"] += 1
        else:
            baseline_total += 1
            entry["baseline_total"] += 1
            if not pass_fail:
                baseline_fail += 1
                entry["baseline_fail"] += 1

    shift_rate = shift_fail / shift_total if shift_total > 0 else 0.0
    baseline_rate = baseline_fail / baseline_total if baseline_total > 0 else 0.0

    open_items: list[str] = []
    data_breakdown = []
    for (part_id, characteristic_name), entry in per_char.items():
        c_shift_rate = entry["shift_fail"] / entry["shift_total"] if entry["shift_total"] > 0 else 0.0
        c_baseline_rate = entry["baseline_fail"] / entry["baseline_total"] if entry["baseline_total"] > 0 else 0.0
        c_is_spike = engine.is_spike(entry["shift_total"], c_shift_rate, c_baseline_rate)
        data_breakdown.append(
            {
                "part_id": part_id,
                "characteristic_name": characteristic_name,
                "shift_rate": c_shift_rate,
                "baseline_rate": c_baseline_rate,
                "is_spike": c_is_spike,
            }
        )
        if c_is_spike:
            # line_id must be passed through here too (this loop already
            # aggregates per-line via `entry["line_id"]`) — otherwise the
            # onset is picked from the earliest failure across every line
            # this part/characteristic is inspected on, and find_likely_cause
            # below ends up correlating a downtime event on entry["line_id"]
            # against an onset that may have actually come from a different
            # line's records.
            onset = await engine.get_spike_onset(
                db, tenant_id, part_id, characteristic_name, line_id=entry["line_id"] or None
            )
            cause = None
            if onset is not None:
                cause = await engine.find_likely_cause(db, tenant_id, entry["line_id"], onset)
            item = f"{part_id}/{characteristic_name} defect rate spike"
            if cause:
                item += f" — {cause}"
            open_items.append(item)

    if shift_total == 0:
        summary_text = "No inspection records this shift."
    elif engine.is_spike(shift_total, shift_rate, baseline_rate):
        summary_text = (
            f"Defect rate {shift_rate * 100:.1f}% (spike vs {baseline_rate * 100:.1f}% baseline)."
        )
        if open_items:
            summary_text += f" {open_items[0]}."
    else:
        summary_text = f"Defect rate {shift_rate * 100:.1f}% (normal)."

    # PRD example handover: "Lot #4471 held for QC — do not release." Every
    # still-open hold is a standing next-shift action regardless of when it
    # was placed — an incoming shift needs to see it even if it was opened
    # two shifts ago and nobody has released it yet.
    open_holds = await list_holds(db, tenant_id, status="open")
    if open_holds:
        summary_text += f" {len(open_holds)} lot(s) on hold."
        open_items.extend(
            f"Lot {h.lot_number} ({h.part_id}) held for QC — do not release ({h.reason})" for h in open_holds
        )

    return ShiftContribution(
        module="quality",
        summary_text=summary_text,
        data={
            "shift_rate": shift_rate,
            "baseline_rate": baseline_rate,
            "shift_total": shift_total,
            "shift_fail": shift_fail,
            "characteristics": data_breakdown,
            "open_holds": [{"part_id": h.part_id, "lot_number": h.lot_number, "reason": h.reason} for h in open_holds],
        },
        open_items=open_items,
    )


# ---------------------------------------------------------------------------
# Chat tool
# ---------------------------------------------------------------------------

class QualityTrendArgs(BaseModel):
    part_id: str
    characteristic_name: str | None = None
    # Lets "any quality issues on Line 3 today?" scope to that line — a part
    # can be inspected on more than one line, and without this the rate
    # blends every line's inspections together.
    line_id: str | None = None


async def get_quality_trend(
    db: AsyncSession,
    tenant_id: int,
    part_id: str,
    characteristic_name: str | None = None,
    line_id: str | None = None,
) -> dict:
    conditions = [Characteristic.tenant_id == tenant_id, Characteristic.part_id == part_id]
    if characteristic_name:
        conditions.append(Characteristic.characteristic_name == characteristic_name)
    if line_id:
        conditions.append(Characteristic.line_id == line_id)
    char = await db.scalar(select(Characteristic).where(*conditions).limit(1))
    resolved_line_id = line_id or (char.line_id if char else None) or None
    station_id = char.station_id if char else None

    trend = await engine.compute_defect_trend(
        db, tenant_id, part_id, characteristic_name, line_id=resolved_line_id, station_id=station_id
    )
    root_cause = None
    drift = None
    if char is not None:
        drift = await engine.compute_tolerance_drift(
            db, tenant_id, char.part_id, char.characteristic_name, char.nominal_value, char.tolerance,
            line_id=resolved_line_id, station_id=station_id,
        )
        if trend["is_spike"]:
            onset = await engine.get_spike_onset(
                db, tenant_id, part_id, characteristic_name, line_id=resolved_line_id, station_id=station_id
            )
            if onset is not None:
                root_cause = await engine.find_likely_cause(db, tenant_id, char.line_id, onset, station_id=station_id)
    return {
        **trend,
        "root_cause": root_cause,
        "tolerance_drift": drift,
        "freshness": await get_freshness(db, tenant_id, "quality"),
    }


register_tool(
    ChatToolSpec(
        name="quality_defect_trend",
        description=(
            "Defect rate trend vs baseline for a part/characteristic, with likely root cause if a spike "
            "is detected."
        ),
        args_schema=QualityTrendArgs,
        fn=get_quality_trend,
    )
)


class ListCharacteristicsArgs(BaseModel):
    pass


async def list_characteristics_tool(db: AsyncSession, tenant_id: int) -> dict:
    chars = await list_characteristics(db, tenant_id)
    return {
        "characteristics": [
            {
                "part_id": c.part_id,
                "characteristic_name": c.characteristic_name,
                "line_id": c.line_id,
                "station_id": c.station_id,
                "nominal_value": c.nominal_value,
                "tolerance": c.tolerance,
            }
            for c in chars
        ]
    }


register_tool(
    ChatToolSpec(
        name="quality_list_characteristics",
        description="Lists every configured quality characteristic (part, characteristic name, line/station, nominal+tolerance) for this tenant.",
        args_schema=ListCharacteristicsArgs,
        fn=list_characteristics_tool,
    )
)


class ListHoldsArgs(BaseModel):
    pass


async def list_open_holds_tool(db: AsyncSession, tenant_id: int) -> dict:
    holds = await list_holds(db, tenant_id, status="open")
    return {
        "open_holds": [
            {"part_id": h.part_id, "lot_number": h.lot_number, "reason": h.reason, "created_at": h.created_at.isoformat()}
            for h in holds
        ]
    }


register_tool(
    ChatToolSpec(
        name="quality_list_open_holds",
        description="Lists every lot/batch currently on hold for QC (part, lot number, reason) — these must not be released.",
        args_schema=ListHoldsArgs,
        fn=list_open_holds_tool,
    )
)


# ---------------------------------------------------------------------------
# Load sample data (BRD §5.1/§2.1). P-100/bore diameter on LINE-3, Station 2 —
# the same line/station Production's sample data uses for its "Tooling
# change" downtime event. The defect spike's onset is anchored 1 hour after
# that event (both computed from the same "yesterday 06:00 shift start"
# calendar math) so the root-cause correlation in §4.5/§6.6 genuinely finds
# it when both modules' sample data are loaded, rather than a canned answer.
# ---------------------------------------------------------------------------


async def load_sample_data(db: AsyncSession, tenant_id: int, user_id: int) -> dict:
    now = datetime.utcnow()

    existing = await db.scalar(
        select(Characteristic).where(Characteristic.tenant_id == tenant_id, Characteristic.part_id == "P-100")
    )
    if existing:
        return {"characteristics_seeded": [], "inspection_records_seeded": 0, "note": "already seeded"}

    char = Characteristic(
        tenant_id=tenant_id,
        part_id="P-100",
        characteristic_name="bore diameter",
        nominal_value=25.0,
        tolerance=0.5,
        inspection_type="manual gauge",
        line_id="LINE-3",
        station_id="Station 2",
        defect_categories=["surface scratch", "burr", "dimension out-of-spec"],
    )
    db.add(char)
    await db.flush()

    yesterday_start = (now - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

    def rec(ts, measured, passed, defect=None):
        return InspectionRecord(
            tenant_id=tenant_id,
            part_id="P-100",
            timestamp=ts,
            characteristic_name="bore diameter",
            measured_value=measured,
            pass_fail=passed,
            defect_type=defect,
            line_id="LINE-3",
            station_id="Station 2",
            inspector="Auto QC",
        )

    records = [
        # Baseline (> RECENT_WINDOW_DAYS=3 ago): low defect rate, measured
        # values close to nominal.
        rec(yesterday_start - timedelta(days=9), 25.02, True),
        rec(yesterday_start - timedelta(days=8), 24.98, True),
        rec(yesterday_start - timedelta(days=7), 25.05, True),
        rec(yesterday_start - timedelta(days=6), 25.03, True),
        rec(yesterday_start - timedelta(days=5), 25.06, False, "burr"),
        # Recent (last 3 days): defect-rate spike + measurements drifting
        # toward the tolerance limit. First fail (onset) is 1 hour after
        # Production's tooling-change event on the same line/station.
        # Mostly "surface scratch" (4 of 5 recent fails = 80%) so the demo
        # reproduces the BRD's own §4.5 example ("82% are 'surface scratch'")
        # instead of a different defect story.
        rec(yesterday_start + timedelta(hours=5), 25.42, False, "surface scratch"),
        rec(yesterday_start + timedelta(hours=5, minutes=30), 25.44, False, "surface scratch"),
        rec(yesterday_start + timedelta(hours=8), 25.40, True),
        rec(yesterday_start + timedelta(hours=10), 25.44, False, "surface scratch"),
        rec(yesterday_start + timedelta(hours=12), 25.46, False, "burr"),
        rec(now - timedelta(hours=20), 25.41, True),
        rec(now - timedelta(hours=14), 25.45, False, "surface scratch"),
        rec(now - timedelta(hours=6), 25.43, True),
        rec(now - timedelta(hours=2), 25.47, True),
    ]
    db.add_all(records)
    await db.commit()

    from app.core.ingestion import touch_freshness
    await touch_freshness(db, tenant_id, "quality")

    return {"characteristics_seeded": ["P-100/bore diameter"], "inspection_records_seeded": len(records)}
