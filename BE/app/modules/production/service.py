from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ChatToolSpec, ModuleSummary, ShiftContribution, register_tool
from app.core.freshness import get_freshness
from app.core.ingestion import CSVSpec, ColumnSpec, touch_freshness
from app.core.models_shared import ModuleFreshness
from app.modules.production import engine
from app.modules.production.engine import get_downtime_events  # noqa: F401 — re-exported: the cross-module
# contract (see DEV_BRIEF_SELF.md 4/5.2 and Quality's engine.py) is
# `app.modules.production.service.get_downtime_events`; the real
# implementation lives in engine.py alongside compute_line_metrics, so it's
# re-exported here rather than duplicated.
from app.modules.production.models import Line, OutputLog
from app.modules.production.schemas import LineCreate, LineUpdate


class LineHasOutputLogsError(Exception):
    """Raised by delete_line when the line has output-log history — deleting
    it would either FK-violate or silently orphan/destroy operational data,
    so we refuse instead (router turns this into a 409).
    """


class DuplicateLineCodeError(Exception):
    """Raised by create_line/update_line on a (tenant_id, line_code) clash —
    pre-checked so it surfaces as a clean 400, mirroring auth.service's
    duplicate-email AuthError pattern, instead of a bare IntegrityError 500.
    """

# Thresholds used by get_summary/get_shift_contribution to classify status.
# Documented assumption (no explicit spec value given):
#   critical: OEE < 60%  OR  behind target by more than 20% of shift target
#   warning:  OEE < 75%  OR  behind target by more than 5% of shift target
#   else ok
OEE_CRITICAL_THRESHOLD = 0.60
OEE_WARNING_THRESHOLD = 0.75
GAP_PCT_CRITICAL_THRESHOLD = -20.0
GAP_PCT_WARNING_THRESHOLD = -5.0


def today_window() -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return start, end


# ---------------------------------------------------------------------------
# Line config CRUD
# ---------------------------------------------------------------------------


async def list_lines(db: AsyncSession, tenant_id: int) -> list[Line]:
    rows = await db.scalars(select(Line).where(Line.tenant_id == tenant_id).order_by(Line.id))
    return list(rows.all())


async def get_line(db: AsyncSession, tenant_id: int, line_id: int) -> Line | None:
    return await db.scalar(select(Line).where(Line.tenant_id == tenant_id, Line.id == line_id))


async def get_line_by_code(db: AsyncSession, tenant_id: int, line_code: str) -> Line | None:
    return await db.scalar(select(Line).where(Line.tenant_id == tenant_id, Line.line_code == line_code))


async def line_code_exists(db: AsyncSession, tenant_id: int, line_code: str) -> bool:
    """fk_checks callback shape required by core.ingestion.CSVSpec:
    async (db, tenant_id, value) -> bool.
    """
    return await get_line_by_code(db, tenant_id, line_code) is not None


async def check_station_belongs_to_line(db: AsyncSession, tenant_id: int, row: dict) -> str | None:
    """row_checks callback (core.ingestion.CSVSpec): a station_id must be one
    of the specific line's registered stations, not just any string — this is
    a cross-column check (needs line_id + station_id together), so it can't be
    expressed as a single-column fk_check.
    """
    line_code = row.get("line_id")
    station_id = row.get("station_id")
    if not line_code or not station_id:
        return None  # missing-required-value errors are already reported elsewhere
    line = await get_line_by_code(db, tenant_id, line_code)
    if line is None:
        return None  # unknown line_id is already reported by the fk_check
    if station_id not in line.stations:
        return f"station '{station_id}' is not registered on line '{line_code}' (known stations: {', '.join(line.stations) or 'none'})"
    return None


async def create_line(db: AsyncSession, tenant_id: int, payload: LineCreate) -> Line:
    if await line_code_exists(db, tenant_id, payload.line_code):
        raise DuplicateLineCodeError(f"line_code '{payload.line_code}' already exists for this tenant")
    line = Line(tenant_id=tenant_id, **payload.model_dump())
    db.add(line)
    await db.commit()
    await db.refresh(line)
    return line


async def update_line(db: AsyncSession, tenant_id: int, line_id: int, payload: LineUpdate) -> Line | None:
    line = await get_line(db, tenant_id, line_id)
    if not line:
        return None
    new_code = payload.line_code
    if new_code is not None and new_code != line.line_code:
        existing = await get_line_by_code(db, tenant_id, new_code)
        if existing is not None:
            raise DuplicateLineCodeError(f"line_code '{new_code}' already exists for this tenant")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(line, field, value)
    await db.commit()
    await db.refresh(line)
    return line


async def delete_line(db: AsyncSession, tenant_id: int, line_id: int) -> bool:
    line = await get_line(db, tenant_id, line_id)
    if not line:
        return False
    has_logs = await db.scalar(
        select(OutputLog.id).where(OutputLog.tenant_id == tenant_id, OutputLog.line_id == line_id).limit(1)
    )
    if has_logs is not None:
        raise LineHasOutputLogsError(f"line {line_id} has existing output-log history")
    await db.delete(line)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Line config CSV import
# ---------------------------------------------------------------------------

async def _check_line_exists_for_upsert(db: AsyncSession, tenant_id: int, parsed: dict) -> str | None:
    code = parsed.get("line_code")
    if not code:
        return None
    line = await get_line_by_code(db, tenant_id, code)
    if line is not None:
        return f"line_code '{code}' already exists — will be updated on commit"
    return None


def _parse_semicolon_list(value: str | None) -> list[str]:
    """Parse semicolon-delimited string into a list: 'S1;S2;S3' -> ['S1','S2','S3']."""
    if not value or not str(value).strip():
        return []
    return [s.strip() for s in str(value).split(";") if s.strip()]


LINE_CSV_SPEC = CSVSpec(
    module="production",
    columns=[
        ColumnSpec(name="line_code", dtype="str"),
        ColumnSpec(name="name", dtype="str"),
        ColumnSpec(name="stations", dtype="str", required=False),
        ColumnSpec(name="products", dtype="str", required=False),
        ColumnSpec(name="shift_target_units", dtype="int", required=False),
        ColumnSpec(name="ideal_cycle_time_seconds", dtype="float", required=False),
    ],
    row_warnings=[_check_line_exists_for_upsert],
)


async def commit_lines_config(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> tuple[int, int]:
    """Upsert lines from CSV: create new, update existing by line_code."""
    created = 0
    updated = 0
    for row in valid_rows:
        existing = await get_line_by_code(db, tenant_id, row["line_code"])
        if existing is not None:
            existing.name = row["name"]
            existing.stations = _parse_semicolon_list(row.get("stations"))
            existing.products = _parse_semicolon_list(row.get("products"))
            existing.shift_target_units = row.get("shift_target_units") or 0
            existing.ideal_cycle_time_seconds = row.get("ideal_cycle_time_seconds") or 0.0
            updated += 1
        else:
            db.add(
                Line(
                    tenant_id=tenant_id,
                    line_code=row["line_code"],
                    name=row["name"],
                    stations=_parse_semicolon_list(row.get("stations")),
                    products=_parse_semicolon_list(row.get("products")),
                    shift_target_units=row.get("shift_target_units") or 0,
                    ideal_cycle_time_seconds=row.get("ideal_cycle_time_seconds") or 0.0,
                )
            )
            created += 1
    await db.commit()
    return created, updated


# ---------------------------------------------------------------------------
# Output logs (operational) — the DB Import / continuous-sync target for
# production data, mirroring the pattern every other operational entity
# (sensor readings, maintenance history, quality inspections, inventory
# movements) already uses. Defined here (not router.py) so db_import/service.py
# can import the spec + commit function without a circular import, same as
# every other module's operational entity.
# ---------------------------------------------------------------------------

OUTPUT_LOG_CSV_HEADER = (
    "line_id,station_id,timestamp,units_produced,units_good,units_reject,"
    "run_state,downtime_minutes,downtime_reason"
)

OUTPUT_LOG_CSV_SPEC = CSVSpec(
    module="production",
    columns=[
        ColumnSpec("line_id", "str", required=True),
        ColumnSpec("station_id", "str", required=True),
        ColumnSpec("timestamp", "datetime", required=True),
        ColumnSpec("units_produced", "int", required=True),
        ColumnSpec("units_good", "int", required=True),
        ColumnSpec("units_reject", "int", required=True),
        ColumnSpec("run_state", "enum", required=True, enum_values=["run", "idle", "stop"]),
        ColumnSpec("downtime_minutes", "float", required=False),
        ColumnSpec("downtime_reason", "str", required=False),
    ],
    fk_checks={"line_id": line_code_exists},
    row_checks=[check_station_belongs_to_line],
)


async def commit_output_log_rows(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> int:
    """Shared by the CSV upload endpoint (production/router.py) and the
    DB Import / continuous-sync path (db_import/service.py) — output logs are
    append-only (no upsert-by-key the way config entities have), so this is
    just a straight insert per valid row."""
    committed = 0
    for row in valid_rows:
        line = await get_line_by_code(db, tenant_id, row["line_id"])
        if not line:
            continue  # already fk-checked upstream; defensive only
        db.add(
            OutputLog(
                tenant_id=tenant_id,
                line_id=line.id,
                station_id=row["station_id"],
                timestamp=row["timestamp"],
                units_produced=row.get("units_produced") or 0,
                units_good=row.get("units_good") or 0,
                units_reject=row.get("units_reject") or 0,
                run_state=row.get("run_state") or "run",
                downtime_minutes=row.get("downtime_minutes") or 0.0,
                downtime_reason=row.get("downtime_reason"),
            )
        )
        committed += 1
    await db.commit()
    await touch_freshness(db, tenant_id, "production")
    return committed


# ---------------------------------------------------------------------------
# Dashboard / shift-report contracts
# ---------------------------------------------------------------------------


async def get_summary(db: AsyncSession, tenant_id: int) -> ModuleSummary:
    lines = await list_lines(db, tenant_id)

    freshness = await db.scalar(
        select(ModuleFreshness).where(ModuleFreshness.tenant_id == tenant_id, ModuleFreshness.module == "production")
    )
    last_updated_at = freshness.last_updated_at if freshness else None
    cadence_hours = freshness.expected_cadence_hours if freshness else None
    is_stale = True
    if freshness:
        is_stale = (datetime.utcnow() - freshness.last_updated_at) > timedelta(hours=freshness.expected_cadence_hours)

    if not lines:
        return ModuleSummary(
            module="production",
            title="Production",
            status="ok",
            headline="No lines configured",
            metrics=[{"label": "Lines", "value": "0"}],
            last_updated_at=last_updated_at,
            is_stale=is_stale,
            expected_cadence_hours=cadence_hours,
            drilldown_path="/production",
        )

    start, end = today_window()
    per_line = []
    for line in lines:
        m = await engine.compute_line_metrics(db, tenant_id, line.id, start, end)
        gap_pct = (m["gap_to_target"] / line.shift_target_units * 100) if line.shift_target_units > 0 else 0.0
        per_line.append((line, m, gap_pct))

    # BRD §5.2: "missing expected data shown as a gap, not a zero" — a line
    # with no output logged yet today isn't "critical/behind," it's unknown;
    # only lines that actually reported data feed the status/worst-line calc.
    reporting = [(line, m, gap_pct) for line, m, gap_pct in per_line if m["has_data"]]
    no_data_count = len(per_line) - len(reporting)

    if not reporting:
        return ModuleSummary(
            module="production",
            title="Production",
            status="ok",
            headline="No production data logged for today yet",
            metrics=[
                {"label": "Lines", "value": str(len(lines))},
                {"label": "Avg OEE", "value": "—"},
            ],
            last_updated_at=last_updated_at,
            is_stale=is_stale,
            expected_cadence_hours=cadence_hours,
            alerts_count=None,
            drilldown_path="/production",
        )

    worst = min(reporting, key=lambda t: t[2])  # most negative gap_pct = furthest behind
    worst_line, worst_metrics, worst_gap_pct = worst

    status = "ok"
    alerts_count = 0
    for _, m, gap_pct in reporting:
        line_critical = m["oee"] < OEE_CRITICAL_THRESHOLD or gap_pct <= GAP_PCT_CRITICAL_THRESHOLD
        line_warning = not line_critical and (m["oee"] < OEE_WARNING_THRESHOLD or gap_pct <= GAP_PCT_WARNING_THRESHOLD)
        if line_critical:
            status = "critical"
            alerts_count += 1
        elif line_warning:
            # A line already flagged critical elsewhere shouldn't be
            # downgraded to "warning" overall, but a warning-level line still
            # counts toward alerts_count — previously only critical lines
            # did, so the dashboard's alert-sort undercounted warnings.
            if status != "critical":
                status = "warning"
            alerts_count += 1

    avg_oee = sum(m["oee"] for _, m, _ in reporting) / len(reporting)

    if status == "ok":
        headline = "All lines on target"
    else:
        behind_word = "behind" if worst_gap_pct < 0 else "ahead of"
        headline = f"{worst_line.name} {abs(round(worst_gap_pct))}% {behind_word} target, OEE {round(worst_metrics['oee'] * 100)}%"
        # BRD §4.2's own example leads with the "why" ("Main drag: Station 3,
        # two unplanned stops (34 min) at 11:00-11:40"), not just the gap/OEE
        # numbers — name the worst line's top downtime driver here too, not
        # only on drill-down.
        top_pareto = worst_metrics.get("downtime_pareto") or []
        if top_pareto:
            drag = top_pareto[0]
            headline += f" — main drag: {drag['station_id']} ({drag['downtime_reason']}, {round(drag['downtime_minutes'])}min)"
    if no_data_count:
        headline += f" ({no_data_count} line{'s' if no_data_count != 1 else ''} not yet reporting today)"

    return ModuleSummary(
        module="production",
        title="Production",
        status=status,
        headline=headline,
        metrics=[
            {"label": "Lines", "value": str(len(lines))},
            {"label": "Avg OEE", "value": f"{round(avg_oee * 100)}%"},
        ],
        last_updated_at=last_updated_at,
        is_stale=is_stale,
        expected_cadence_hours=cadence_hours,
        alerts_count=alerts_count if reporting else None,
        drilldown_path="/production",
    )


async def get_shift_contribution(db: AsyncSession, tenant_id: int, start: datetime, end: datetime) -> ShiftContribution:
    lines = await list_lines(db, tenant_id)
    if not lines:
        return ShiftContribution(module="production", summary_text="No lines configured", data={}, open_items=[])

    data: dict = {}
    total_units = 0
    total_target = 0
    total_downtime = 0.0
    oee_values: list[float] = []
    pareto_acc: dict[tuple[str, str], float] = {}
    open_items: list[str] = []

    for line in lines:
        m = await engine.compute_line_metrics(db, tenant_id, line.id, start, end)
        data[line.line_code] = m
        total_units += m["total_units"]
        total_target += m["shift_target_units"]
        total_downtime += m["downtime_minutes"]
        oee_values.append(m["oee"])
        for entry in m["downtime_pareto"]:
            key = (entry["station_id"], entry["downtime_reason"])
            pareto_acc[key] = pareto_acc.get(key, 0.0) + entry["downtime_minutes"]

        gap_pct = (m["gap_to_target"] / line.shift_target_units * 100) if line.shift_target_units > 0 else 0.0
        if gap_pct <= GAP_PCT_WARNING_THRESHOLD:
            open_items.append(f"{line.name} behind target ({m['total_units']}/{m['shift_target_units']} units)")

    avg_oee = sum(oee_values) / len(oee_values) if oee_values else 0.0
    pct_of_target = round(total_units / total_target * 100) if total_target > 0 else 0

    top_reasons = sorted(
        ({"station_id": s, "downtime_reason": r, "downtime_minutes": mins} for (s, r), mins in pareto_acc.items()),
        key=lambda d: d["downtime_minutes"],
        reverse=True,
    )[:2]
    reasons_text = ", ".join(
        f"{e['station_id']} {e['downtime_reason']} {round(float(e['downtime_minutes']))}min" for e in top_reasons
    )

    summary_text = (
        f"{total_units:,} / {total_target:,} units ({pct_of_target}%). "
        f"OEE {round(avg_oee * 100)}%. "
        f"Downtime {round(total_downtime)} min"
        + (f" ({reasons_text})" if reasons_text else "")
        + "."
    )

    return ShiftContribution(module="production", summary_text=summary_text, data=data, open_items=open_items)


# ---------------------------------------------------------------------------
# Chatbot tool
# ---------------------------------------------------------------------------


class ProductionGapArgs(BaseModel):
    line_id: str  # this is the line_code, not the numeric id


async def _resolve_line(db: AsyncSession, tenant_id: int, line_id_or_name: str) -> Line | None:
    """Callers (chat included) often say the line's plain name ("High-Precision
    Filler") rather than its code ("FILL-HP") — resolve against both before
    giving up, same convention as shift_reports' schedule-name lookup.
    """
    exact = await get_line_by_code(db, tenant_id, line_id_or_name)
    if exact is not None:
        return exact

    from app.core.dimension_resolver import resolve

    lines = await list_lines(db, tenant_id)
    by_name = {l.name: l for l in lines}
    result = resolve(line_id_or_name, list(by_name.keys()))
    if result.matched:
        return by_name[result.matched]
    return None


async def get_production_gap(db: AsyncSession, tenant_id: int, line_id: str) -> dict:
    line = await _resolve_line(db, tenant_id, line_id)
    if not line:
        return {"error": f"No line found matching '{line_id}'. Use production_list_lines to see valid line codes/names."}

    start, end = today_window()
    m = await engine.compute_line_metrics(db, tenant_id, line.id, start, end)
    return {
        "line_id": line.line_code,
        "line_name": line.name,
        "total_units": m["total_units"],
        "shift_target_units": m["shift_target_units"],
        "gap_to_target": m["gap_to_target"],
        "oee": m["oee"],
        "availability": m["availability"],
        "performance": m["performance"],
        "quality": m["quality"],
        # False means no output has been logged for today's window yet — the
        # figures above are all zero by absence of data, not a real reading;
        # the chatbot should say "no data logged yet" rather than "0%/behind."
        "has_data": m["has_data"],
        "freshness": await get_freshness(db, tenant_id, "production"),
    }


register_tool(
    ChatToolSpec(
        name="production_gap_to_target",
        description=(
            "Actual vs target output and OEE for a given line, today. Accepts either the exact line "
            "code or the line's plain-language name."
        ),
        args_schema=ProductionGapArgs,
        fn=get_production_gap,
    )
)


class ProductionDowntimeArgs(BaseModel):
    line_id: str  # line_code or plain-language name, same convention as ProductionGapArgs


def _primary_oee_driver(m: dict) -> str:
    """Names which of availability/performance/quality is dragging OEE down
    the most — the PRD's own chatbot example makes this call explicitly
    ("Availability is the issue, not speed or quality") rather than just
    reporting the three numbers and leaving the reader to compare them.
    """
    factors = {"availability": m["availability"], "performance": m["performance"], "quality": m["quality"]}
    worst = min(factors, key=lambda k: factors[k])
    if factors[worst] >= 0.97:
        return "All three OEE factors (availability, performance, quality) are close to normal."
    others = [k for k in factors if k != worst]
    return f"{worst.capitalize()} is the issue, not {' or '.join(others)} — those are both normal."


async def get_production_downtime_detail(db: AsyncSession, tenant_id: int, line_id: str) -> dict:
    line = await _resolve_line(db, tenant_id, line_id)
    if not line:
        return {"error": f"No line found matching '{line_id}'. Use production_list_lines to see valid line codes/names."}

    start, end = today_window()
    m = await engine.compute_line_metrics(db, tenant_id, line.id, start, end)
    stops = await engine.summarize_downtime_stops(db, tenant_id, line.line_code, start, end)

    return {
        "line_id": line.line_code,
        "line_name": line.name,
        "oee": m["oee"],
        "availability": m["availability"],
        "performance": m["performance"],
        "quality": m["quality"],
        "primary_driver": _primary_oee_driver(m) if m["has_data"] else None,
        # Each entry: station_id, stop_count, total_minutes, window_start,
        # window_end, reasons — e.g. "Station 3, two unplanned stops (34 min)
        # at 11:00-11:40", matching the PRD's own worked example verbatim.
        "downtime_stops": stops,
        "has_data": m["has_data"],
        "freshness": await get_freshness(db, tenant_id, "production"),
    }


register_tool(
    ChatToolSpec(
        name="production_downtime_detail",
        description=(
            "Why a line is behind today, broken down by station: which OEE factor (availability/"
            "performance/quality) is the actual drag, plus discrete downtime stops per station (count, "
            "total minutes, and the time window each station's stops occurred in). Use this for "
            "'why is line X behind' questions instead of production_gap_to_target, which only gives "
            "aggregate numbers."
        ),
        args_schema=ProductionDowntimeArgs,
        fn=get_production_downtime_detail,
    )
)


class ListLinesArgs(BaseModel):
    pass


async def list_lines_tool(db: AsyncSession, tenant_id: int) -> dict:
    lines = await list_lines(db, tenant_id)
    return {
        "lines": [
            {"line_code": l.line_code, "name": l.name, "products": l.products, "shift_target_units": l.shift_target_units}
            for l in lines
        ]
    }


register_tool(
    ChatToolSpec(
        name="production_list_lines",
        description="Lists every configured production line (code, name, products, shift target) for this tenant.",
        args_schema=ListLinesArgs,
        fn=list_lines_tool,
    )
)


# ---------------------------------------------------------------------------
# Load sample data (BRD §5.1/§2.1). Line 3 + a tooling-change downtime event
# at 10:30 yesterday — deliberately the same line_code and timing Quality's
# sample data references, so if both are loaded, the root-cause correlation
# (§4.5/§6.6) genuinely finds this event, not a canned answer.
# ---------------------------------------------------------------------------

async def load_sample_data(db: AsyncSession, tenant_id: int, user_id: int) -> dict:
    now = datetime.utcnow()

    existing = await get_line_by_code(db, tenant_id, "LINE-3")
    if existing:
        return {"lines_seeded": [], "output_logs_seeded": 0, "note": "already seeded"}

    line = Line(
        tenant_id=tenant_id,
        line_code="LINE-3",
        name="Line 3",
        stations=["Station 1", "Station 2", "Station 3"],
        products=["Widget-A"],
        shift_target_units=7200,
        ideal_cycle_time_seconds=3.8,
    )
    db.add(line)
    await db.flush()

    shift_start = (now - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    logs = []
    # Steady running hours through the shift, each station producing close to
    # target, until the 10:30 tooling change stop on Station 2.
    for hour_offset in range(0, 8):
        ts = shift_start + timedelta(hours=hour_offset)
        for station in line.stations:
            is_tooling_change = station == "Station 2" and hour_offset == 4  # 10:30-ish
            logs.append(
                OutputLog(
                    tenant_id=tenant_id,
                    line_id=line.id,
                    station_id=station,
                    timestamp=ts,
                    units_produced=280 if not is_tooling_change else 180,
                    units_good=278 if not is_tooling_change else 178,
                    units_reject=2,
                    run_state="stop" if is_tooling_change else "run",
                    downtime_minutes=15.0 if is_tooling_change else 0.0,
                    downtime_reason="Tooling change" if is_tooling_change else None,
                )
            )
    db.add_all(logs)
    await db.commit()

    from app.core.ingestion import touch_freshness

    await touch_freshness(db, tenant_id, "production")

    return {"lines_seeded": ["LINE-3"], "output_logs_seeded": len(logs)}
