"""Database Import — Cloud DB path. Reuses the exact same target specs and
commit functions the CSV config-import endpoints already use (see
core.ingestion / each module's ASSET_CSV_SPEC etc.) — only the *extraction*
step (connect to a customer database, read rows) is new; mapping,
validation, editable preview, and commit are the same shared engine.
"""
from __future__ import annotations

import difflib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_crypto import decrypt_credential, encrypt_credential
from app.core.db_adapters import ConnectionParams, DatabaseAdapter, TableInfo, get_adapter_class
from app.core.ingestion import CSVSpec, touch_freshness, validate_records
from app.modules.db_import.models import ConnectorRegistration, DbConnection, SyncSchedule
from app.modules.db_import.schemas import DbConnectionInput

SAMPLE_ROW_LIMIT = 25

# After this many consecutive failed sync ticks, nudge an admin instead of
# failing silently forever — reuses the existing generic alert path.
SYNC_FAILURE_ALERT_THRESHOLD = 3

# Floor for interval_minutes — without this, an admin could accidentally set
# a 1-minute sync that hammers their production database. 5 minutes already
# matches how often most plant historians actually write new sensor rows, so
# going tighter adds load without adding real signal.
MIN_SYNC_INTERVAL_MINUTES = 5


class DbImportError(Exception):
    """Raised for request-shape problems (unknown entity, missing
    connection details) — router turns this into a 400.
    """


# ---------------------------------------------------------------------------
# Importable entities — the target side of Database Import. Deliberately the
# same five configuration entities the CSV/Excel import already covers
# (Assets, Lines, Items, Characteristics, Shift Schedules); DB Import is
# another *source* for the exact same targets, not a new set of targets.
# ---------------------------------------------------------------------------

@dataclass
class ImportableEntity:
    key: str
    label: str
    module: str  # for touch_freshness + audit log entity_type
    spec: CSVSpec
    commit_fn: Callable[[AsyncSession, int, list[dict]], Awaitable[tuple[int, int]]]
    # Table-name keywords used by recommend_tables' deterministic scoring —
    # no AI/LLM involved, matching the CSV auto-mapper's own approach.
    table_keywords: list[str] = field(default_factory=list)


async def _commit_inspections_wrapped(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> tuple[int, int]:
    """Adapts quality's commit_inspection_rows (returns (count, touched-set))
    to the (created, updated) shape db_import's commit endpoint/run_sync
    expect, and replicates the same post-commit spike re-check its own CSV
    upload endpoint already does — see quality/router.py's commit endpoint.
    """
    from app.modules.quality.service import check_and_alert_spikes, commit_inspection_rows

    committed, touched = await commit_inspection_rows(db, tenant_id, valid_rows)
    await check_and_alert_spikes(db, tenant_id, touched)
    return committed, 0


async def _commit_stock_movements_wrapped(db: AsyncSession, tenant_id: int, valid_rows: list[dict]) -> tuple[int, int]:
    """Same adaptation for inventory's commit_stock_movements — replicates
    the scoped low-stock re-alert its own CSV upload endpoint already does.
    """
    from app.modules.inventory.service import commit_stock_movements, resync_low_stock_alerts

    committed, touched_item_ids = await commit_stock_movements(db, tenant_id, valid_rows)
    await resync_low_stock_alerts(db, tenant_id, touched_item_ids)
    return committed, 0


def _load_entities() -> dict[str, ImportableEntity]:
    # Imported lazily (inside a function, not at module import time) to
    # dodge a circular import: those modules' service.py files don't import
    # db_import, but importing them at db_import/service.py's own import
    # time would run before app.core.db_adapters and other core modules
    # those services transitively touch have finished initializing.
    from app.modules.inventory.service import ITEM_CSV_SPEC, STOCK_MOVEMENT_CSV_SPEC, commit_items_config
    from app.modules.predictive_maintenance.service import (
        ASSET_CSV_SPEC,
        ASSET_METRIC_RANGE_CSV_SPEC,
        MAINTENANCE_CSV_SPEC,
        READINGS_CSV_SPEC,
        commit_asset_metric_ranges,
        commit_assets_config,
        commit_maintenance_history,
        commit_readings,
    )
    from app.modules.production.service import (
        LINE_CSV_SPEC,
        OUTPUT_LOG_CSV_SPEC,
        commit_lines_config,
        commit_output_log_rows,
    )
    from app.modules.quality.service import (
        CHARACTERISTIC_CSV_SPEC,
        INSPECTION_RECORD_CSV_SPEC,
        commit_characteristics_config,
    )
    from app.modules.shift_reports.service import SHIFT_SCHEDULE_CSV_SPEC, commit_shift_schedules_config

    entities = [
        ImportableEntity(
            key="assets", label="Assets", module="predictive_maintenance",
            spec=ASSET_CSV_SPEC, commit_fn=commit_assets_config,
            table_keywords=["asset", "machine", "equipment", "device", "unit"],
        ),
        ImportableEntity(
            key="asset_metric_ranges", label="Asset Normal Ranges", module="predictive_maintenance",
            spec=ASSET_METRIC_RANGE_CSV_SPEC, commit_fn=commit_asset_metric_ranges,
            table_keywords=["range", "threshold", "limit", "metric", "spec", "normal"],
        ),
        ImportableEntity(
            key="lines", label="Lines", module="production",
            spec=LINE_CSV_SPEC, commit_fn=commit_lines_config,
            table_keywords=["line", "production_line", "workline", "cell"],
        ),
        ImportableEntity(
            key="items", label="Items", module="inventory",
            spec=ITEM_CSV_SPEC, commit_fn=commit_items_config,
            table_keywords=["item", "sku", "material", "part", "inventory", "stock"],
        ),
        ImportableEntity(
            key="characteristics", label="Characteristics", module="quality",
            spec=CHARACTERISTIC_CSV_SPEC, commit_fn=commit_characteristics_config,
            table_keywords=["characteristic", "quality", "spec", "tolerance", "measurement"],
        ),
        ImportableEntity(
            key="schedules", label="Shift Schedules", module="shift_reports",
            spec=SHIFT_SCHEDULE_CSV_SPEC, commit_fn=commit_shift_schedules_config,
            table_keywords=["shift", "schedule", "roster"],
        ),
        # --- Operational/transactional entities — added for continuous DB
        # sync (see SyncSchedule); config entities above only ever needed a
        # one-off import, but a running plant's own sensor readings,
        # maintenance events, inspections, and stock movements are exactly
        # what an unattended sync is for.
        ImportableEntity(
            key="sensor_readings", label="Sensor Readings", module="predictive_maintenance",
            spec=READINGS_CSV_SPEC, commit_fn=commit_readings,
            table_keywords=["sensor", "reading", "telemetry", "measurement"],
        ),
        ImportableEntity(
            key="maintenance_history", label="Maintenance History", module="predictive_maintenance",
            spec=MAINTENANCE_CSV_SPEC, commit_fn=commit_maintenance_history,
            table_keywords=["maintenance", "repair", "service", "work_order"],
        ),
        ImportableEntity(
            key="quality_inspections", label="Quality Inspections", module="quality",
            spec=INSPECTION_RECORD_CSV_SPEC, commit_fn=_commit_inspections_wrapped,
            table_keywords=["inspection", "quality", "defect", "measurement"],
        ),
        ImportableEntity(
            key="inventory_movements", label="Inventory Movements", module="inventory",
            spec=STOCK_MOVEMENT_CSV_SPEC, commit_fn=_commit_stock_movements_wrapped,
            table_keywords=["movement", "stock", "transaction", "inventory"],
        ),
        ImportableEntity(
            key="production_output", label="Production Output", module="production",
            spec=OUTPUT_LOG_CSV_SPEC, commit_fn=commit_output_log_rows,
            table_keywords=["output", "production", "throughput", "run", "downtime"],
        ),
    ]
    return {e.key: e for e in entities}


_ENTITIES: dict[str, ImportableEntity] | None = None


def get_entity(key: str) -> ImportableEntity:
    global _ENTITIES
    if _ENTITIES is None:
        _ENTITIES = _load_entities()
    try:
        return _ENTITIES[key]
    except KeyError:
        raise DbImportError(f"Unknown importable entity '{key}'")


def list_entities() -> list[dict]:
    global _ENTITIES
    if _ENTITIES is None:
        _ENTITIES = _load_entities()
    return [{"key": e.key, "label": e.label} for e in _ENTITIES.values()]


# ---------------------------------------------------------------------------
# Connection resolution — one-time (default) vs saved persistent connection
# ---------------------------------------------------------------------------

async def resolve_connection_params(db: AsyncSession, tenant_id: int, payload: DbConnectionInput) -> ConnectionParams:
    if payload.connection_id is not None:
        saved = await db.scalar(
            select(DbConnection).where(DbConnection.tenant_id == tenant_id, DbConnection.id == payload.connection_id)
        )
        if saved is None:
            raise DbImportError(f"Saved connection {payload.connection_id} not found")
        saved.last_used_at = datetime.utcnow()
        await db.commit()
        return ConnectionParams(
            host=saved.host,
            port=saved.port,
            username=saved.username,
            password=decrypt_credential(saved.encrypted_password),
            database=saved.database,
            ssl=saved.ssl,
            engine=saved.engine,
        )

    if not payload.host or not payload.port or not payload.username or payload.password is None:
        raise DbImportError("host, port, username, and password are required")

    return ConnectionParams(
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        database=payload.database,
        ssl=payload.ssl,
        engine=payload.engine,
    )


async def save_connection_if_requested(
    db: AsyncSession, tenant_id: int, user_id: int, payload: DbConnectionInput, engine: str
) -> int | None:
    """Opt-in persistent-connection mode: only ever called after a
    successful test_connection, and only when the caller explicitly asked
    for it via save_as — the default path (save_as unset) never reaches
    here, so no credential is stored unless the user deliberately chose to.
    """
    if not payload.save_as or payload.connection_id is not None:
        return None
    if not payload.host or not payload.port or not payload.username or payload.password is None:
        raise DbImportError("host, port, username, and password are required to save a connection")
    conn = DbConnection(
        tenant_id=tenant_id,
        name=payload.save_as,
        engine=engine,
        host=payload.host,
        port=payload.port,
        database=payload.database,
        username=payload.username,
        ssl=payload.ssl,
        encrypted_password=encrypt_credential(payload.password),
        created_by=user_id,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn.id


async def list_saved_connections(db: AsyncSession, tenant_id: int) -> list[DbConnection]:
    return list(await db.scalars(select(DbConnection).where(DbConnection.tenant_id == tenant_id).order_by(DbConnection.name)))


async def delete_saved_connection(db: AsyncSession, tenant_id: int, connection_id: int) -> bool:
    result = await db.execute(
        delete(DbConnection).where(DbConnection.tenant_id == tenant_id, DbConnection.id == connection_id)
    )
    await db.commit()
    return result.rowcount > 0


def build_adapter(params: ConnectionParams) -> DatabaseAdapter:
    if not params.engine:
        raise DbImportError("engine must be resolved (call detect-engine / test-connection first)")
    cls = get_adapter_class(params.engine)
    return cls(params)


# ---------------------------------------------------------------------------
# Intelligent table detection — deterministic name-based scoring, no AI/LLM,
# same philosophy as core.ingestion.auto_map_columns for fields.
# ---------------------------------------------------------------------------

def _normalize_table_name(name: str) -> str:
    return name.lower().replace("_", " ").replace("-", " ").strip()

def _score_table(table_name: str, entity: ImportableEntity) -> tuple[float, str | None]:
    normalized = _normalize_table_name(table_name)
    singular_key = entity.key[:-1] if entity.key.endswith("s") else entity.key
    if singular_key in normalized or entity.label.lower() in normalized:
        return 1.0, f"table name matches '{entity.label}'"
    for kw in entity.table_keywords:
        if kw in normalized:
            return 0.7, f"table name contains '{kw}'"
    ratio = difflib.SequenceMatcher(None, singular_key, normalized.replace(" ", "")).ratio()
    if ratio > 0.5:
        return round(ratio * 0.5, 2), "table name is similar to the target entity"
    return 0.0, None


def recommend_tables(tables: list[TableInfo], entity: ImportableEntity) -> list[TableInfo]:
    for t in tables:
        t.recommendation_score, t.recommendation_reason = _score_table(t.name, entity)
    return sorted(tables, key=lambda t: t.recommendation_score, reverse=True)


# ---------------------------------------------------------------------------
# Continuous sync — re-runs a saved SyncSchedule's mapping on a timer instead
# of once by hand. Cloud-direct schedules pull+commit inline; connector-backed
# schedules enqueue a tagged read_rows job and return — the connector polls
# independently, and handle_sync_job_result finishes the job when the
# connector eventually reports back (see connector_service.submit_job_result).
# ---------------------------------------------------------------------------

class SyncError(Exception):
    """Request-shape problems creating/updating a SyncSchedule — router turns
    this into a 400."""


def _parse_watermark(value: str | None) -> object:
    """The stored watermark is always text (SyncSchedule.last_watermark_value)
    but the column it's compared against usually isn't — passing a bare Python
    str through to the adapter risks a type-mismatched comparison against a
    timestamp/integer column, so recover the likely native type here.
    """
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    return value


async def _mark_sync_failure(db: AsyncSession, schedule: SyncSchedule, error: str) -> None:
    # `error` may have come from a failed statement on this same session
    # (e.g. a constraint violation inside _apply_sync_rows's commit_fn call).
    # Postgres leaves the transaction "aborted" until an explicit rollback —
    # without this, the commit() below would itself raise, silently losing
    # the failure record, and (since the scheduler shares one session across
    # every due schedule in a tick) would poison every schedule after this
    # one too. Harmless no-op when the session was already healthy.
    await db.rollback()
    # rollback() unconditionally expires every attribute on every object in
    # the session (regardless of expire_on_commit) — touching schedule's
    # attributes below without this would trigger an implicit lazy-reload
    # that isn't valid in an async context (MissingGreenlet).
    await db.refresh(schedule)
    schedule.last_status = "failed"
    schedule.last_error = error[:2000]
    schedule.last_synced_at = datetime.utcnow()
    schedule.consecutive_failures += 1
    await db.commit()

    if schedule.consecutive_failures >= SYNC_FAILURE_ALERT_THRESHOLD:
        from app.modules.notifications.service import trigger_generic_alert

        await trigger_generic_alert(
            db,
            schedule.tenant_id,
            module="db_sync",
            title=f"Database sync failing for {schedule.table_name}",
            message=(
                f"Continuous sync for '{schedule.table_name}' has failed {schedule.consecutive_failures} times "
                f"in a row. Latest error: {error[:300]}"
            ),
            dashboard_link="/admin",
        )


async def _apply_sync_rows(db: AsyncSession, schedule: SyncSchedule, target: ImportableEntity, rows: list[dict]) -> None:
    if not rows:
        schedule.last_status = "success"
        schedule.last_synced_at = datetime.utcnow()
        schedule.consecutive_failures = 0
        schedule.last_error = None
        await db.commit()
        return

    # Taken from the raw rows before renaming — read_rows always returns every
    # source column (SELECT *), so the watermark column is present regardless
    # of whether it's one of the entity's mapped fields.
    watermark_values = [r[schedule.watermark_column] for r in rows if r.get(schedule.watermark_column) is not None]

    if schedule.column_mapping:
        rename = {source_col: app_field for app_field, source_col in schedule.column_mapping.items() if source_col}
        mapped_rows = [{rename.get(k, k): v for k, v in row.items()} for row in rows]
    else:
        mapped_rows = rows

    try:
        result = await validate_records(mapped_rows, target.spec, db, schedule.tenant_id)
        # Unattended — always skip rows that fail validation rather than
        # blocking the whole batch on one bad row, matching a CSV upload's
        # skip_invalid=True default.
        await target.commit_fn(db, schedule.tenant_id, result.valid_rows)
        await touch_freshness(db, schedule.tenant_id, target.module)
    except Exception as exc:  # noqa: BLE001 - any failure here is a sync failure, not a crash
        await _mark_sync_failure(db, schedule, str(exc))
        return

    if watermark_values:
        schedule.last_watermark_value = str(max(watermark_values))
    schedule.last_status = "success"
    schedule.last_synced_at = datetime.utcnow()
    schedule.consecutive_failures = 0
    schedule.last_error = None
    await db.commit()

    # Best-effort and deliberately after the state update above commits: the
    # watermark advance is what prevents re-pulling/re-inserting the same
    # rows next tick, so it must land even if audit logging itself fails.
    try:
        from app.core.audit import log_audit

        await log_audit(
            db, schedule.tenant_id, schedule.created_by, action=f"db_import_sync_{schedule.entity}",
            entity_type=schedule.entity, entity_id=schedule.id,
            details=f"rows_pulled={len(rows)} rows_committed={len(result.valid_rows)} rows_skipped={len(result.errors)} table={schedule.table_name}",
        )
    except Exception:
        pass


async def run_sync(db: AsyncSession, schedule: SyncSchedule) -> None:
    target = get_entity(schedule.entity)

    if schedule.connector_id is not None:
        from app.modules.db_import import connector_service

        try:
            await connector_service.create_job(
                db,
                schedule.tenant_id,
                schedule.created_by,
                schedule.connector_id,
                action="read_rows",
                params={
                    "schema_name": schedule.schema_name,
                    "table": schedule.table_name,
                    "since_column": schedule.watermark_column,
                    "since_value": schedule.last_watermark_value,
                    "sync_schedule_id": schedule.id,
                },
            )
            # Mark the tick as "in flight" immediately — otherwise this
            # schedule would still look overdue on the very next scheduler
            # tick (5 min later) and enqueue a second job before the
            # connector has even had a chance to poll for the first one,
            # piling up duplicate jobs if the connector is slow or offline.
            schedule.last_synced_at = datetime.utcnow()
            schedule.last_status = "pending"
            await db.commit()
        except connector_service.ConnectorJobError as exc:
            await _mark_sync_failure(db, schedule, str(exc))
        return  # completion is handled by handle_sync_job_result once the connector reports back

    conn = await db.scalar(
        select(DbConnection).where(DbConnection.tenant_id == schedule.tenant_id, DbConnection.id == schedule.connection_id)
    )
    if conn is None:
        await _mark_sync_failure(db, schedule, "the saved cloud connection for this schedule no longer exists")
        return

    params = ConnectionParams(
        host=conn.host, port=conn.port, username=conn.username,
        password=decrypt_credential(conn.encrypted_password), database=conn.database, ssl=conn.ssl, engine=conn.engine,
    )
    try:
        adapter = build_adapter(params)
        try:
            rows = await adapter.read_rows(
                schedule.schema_name, schedule.table_name,
                since_column=schedule.watermark_column, since_value=_parse_watermark(schedule.last_watermark_value),
            )
        finally:
            await adapter.close()
    except Exception as exc:  # noqa: BLE001 - connection/query failure is a sync failure, not a crash
        await _mark_sync_failure(db, schedule, str(exc))
        return

    await _apply_sync_rows(db, schedule, target, rows)


async def handle_sync_job_result(
    db: AsyncSession, sync_schedule_id: int, status: str, result: dict | list | None, error: str | None
) -> None:
    """Called from connector_service.submit_job_result when a completed job
    carries a sync_schedule_id tag — finishes what run_sync's connector
    branch started, once the connector actually reports back.
    """
    schedule = await db.scalar(select(SyncSchedule).where(SyncSchedule.id == sync_schedule_id))
    if schedule is None:
        return
    if status != "completed":
        await _mark_sync_failure(db, schedule, error or "connector job failed")
        return
    target = get_entity(schedule.entity)
    rows = result if isinstance(result, list) else []
    await _apply_sync_rows(db, schedule, target, rows)


async def list_sync_schedules(db: AsyncSession, tenant_id: int) -> list[SyncSchedule]:
    return list(await db.scalars(select(SyncSchedule).where(SyncSchedule.tenant_id == tenant_id).order_by(SyncSchedule.id)))


async def create_sync_schedule(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    entity: str,
    connection_id: int | None,
    connector_id: int | None,
    schema_name: str | None,
    table_name: str,
    column_mapping: dict,
    watermark_column: str,
    interval_minutes: int,
) -> SyncSchedule:
    if (connection_id is None) == (connector_id is None):
        raise SyncError("exactly one of connection_id or connector_id must be set")
    get_entity(entity)  # raises DbImportError (-> 404) if unknown

    # Ownership checks — without these, a schedule could be created against
    # another tenant's saved connection/connector by guessing its id, and
    # would then pull that tenant's database into this tenant's tables.
    if connection_id is not None:
        owned = await db.scalar(
            select(DbConnection).where(DbConnection.tenant_id == tenant_id, DbConnection.id == connection_id)
        )
        if owned is None:
            raise SyncError(f"connection {connection_id} not found")
    if connector_id is not None:
        owned_connector = await db.scalar(
            select(ConnectorRegistration).where(
                ConnectorRegistration.tenant_id == tenant_id, ConnectorRegistration.id == connector_id
            )
        )
        if owned_connector is None:
            raise SyncError(f"connector {connector_id} not found")

    schedule = SyncSchedule(
        tenant_id=tenant_id,
        connection_id=connection_id,
        connector_id=connector_id,
        entity=entity,
        schema_name=schema_name,
        table_name=table_name,
        column_mapping=column_mapping,
        watermark_column=watermark_column,
        interval_minutes=max(MIN_SYNC_INTERVAL_MINUTES, interval_minutes),
        created_by=user_id,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


async def set_sync_schedule_enabled(db: AsyncSession, tenant_id: int, schedule_id: int, enabled: bool) -> SyncSchedule | None:
    schedule = await db.scalar(
        select(SyncSchedule).where(SyncSchedule.tenant_id == tenant_id, SyncSchedule.id == schedule_id)
    )
    if schedule is None:
        return None
    schedule.enabled = enabled
    await db.commit()
    await db.refresh(schedule)
    return schedule


async def delete_sync_schedule(db: AsyncSession, tenant_id: int, schedule_id: int) -> bool:
    result = await db.execute(
        delete(SyncSchedule).where(SyncSchedule.tenant_id == tenant_id, SyncSchedule.id == schedule_id)
    )
    await db.commit()
    return result.rowcount > 0


async def due_sync_schedules(db: AsyncSession) -> list[SyncSchedule]:
    """Every enabled schedule across every tenant whose interval has elapsed
    since its last run (or that has never run) — called by the scheduler,
    not scoped to one tenant like everything else in this module.
    """
    from datetime import timedelta

    now = datetime.utcnow()
    all_enabled = list(await db.scalars(select(SyncSchedule).where(SyncSchedule.enabled.is_(True))))
    return [
        s for s in all_enabled
        if s.last_synced_at is None or (now - s.last_synced_at) >= timedelta(minutes=s.interval_minutes)
    ]
