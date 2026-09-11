from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.db import get_db
from app.core.db_adapters import AdapterError, PrerequisiteMissingError, list_supported_engines
from app.core.db_adapters.registry import detect_engine
from app.core.deps import get_tenant_id, require_role
from app.core.ingestion import (
    ColumnMeta,
    MappingResult,
    ValidationResult,
    auto_map_columns,
    commit_response,
    enforce_commit_gate,
    touch_freshness,
    validate_records,
)
from app.core.module_registry import ModuleRegistration, register_module
from app.core.rate_limit import limiter
from app.modules.db_import import connector_service, service
from app.modules.db_import.models import ConnectorRegistration
from app.modules.db_import.schemas import (
    CommitRequest,
    ConnectorCreateRequest,
    ConnectorJobCreateRequest,
    ConnectorJobOut,
    ConnectorJobResultRequest,
    ConnectorOut,
    ConnectorRegisterRequest,
    ConnectorRegistrationKeyOut,
    ConnectorTokenOut,
    DbConnectionInput,
    SampleRequest,
    SavedConnectionOut,
    SchemaListOut,
    SyncScheduleCreateRequest,
    SyncScheduleOut,
    SyncScheduleUpdateRequest,
    TableDetailRequest,
    TableListRequest,
    TableOut,
    TableValidateRequest,
    TestConnectionResult,
)

router = APIRouter()
_connector_bearer = HTTPBearer()


async def get_current_connector(
    credentials: HTTPAuthorizationCredentials = Depends(_connector_bearer),
    db: AsyncSession = Depends(get_db),
) -> ConnectorRegistration:
    """Auth dependency for connector-initiated endpoints (job polling/result
    submission) — parallels core.deps.get_current_user, but for the
    connector's own long-lived bearer token instead of a dashboard user's
    JWT (see connector_service.py's module docstring for why they differ).
    """
    try:
        return await connector_service.authenticate_connector(db, credentials.credentials)
    except connector_service.ConnectorAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@router.get("/health")
async def health():
    return {"module": "db_import", "status": "ok"}


@router.get("/engines")
async def get_engines(_tenant_id: int = Depends(get_tenant_id)):
    """Cloud DB Import never offers a local_only (file-based) engine — those
    are only ever reachable through the Local Connector.
    """
    return [e for e in list_supported_engines() if not e["local_only"]]


@router.get("/entities")
async def get_entities(_tenant_id: int = Depends(get_tenant_id)):
    return service.list_entities()


# ---------------------------------------------------------------------------
# Connection test / detection / optional persistence
# ---------------------------------------------------------------------------

@router.post("/test-connection", response_model=TestConnectionResult)
async def test_connection(
    payload: DbConnectionInput,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    try:
        params = await service.resolve_connection_params(db, user.tenant_id, payload)
    except service.DbImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        result = await detect_engine(params)
    except PrerequisiteMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except AdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not result["detected"]:
        raise HTTPException(status_code=400, detail="Could not connect — check host, port, and credentials.")
    if result["ambiguous"]:
        raise HTTPException(
            status_code=409,
            detail={"message": "More than one supported engine answered on this host/port — pick one explicitly.", "candidates": result["detected"]},
        )

    engine = result["detected"][0]
    saved_id = None
    try:
        saved_id = await service.save_connection_if_requested(db, user.tenant_id, user.id, payload, engine)
    except service.DbImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await log_audit(
        db, user.tenant_id, user.id, action="db_import_test_connection", entity_type="db_connection",
        details=f"engine={engine} host={payload.host or '(saved connection)'} saved={saved_id is not None}",
    )
    return TestConnectionResult(detected=result["detected"], version=result["version"], ambiguous=False, saved_connection_id=saved_id)


@router.get("/connections", response_model=list[SavedConnectionOut])
async def get_saved_connections(db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    return await service.list_saved_connections(db, user.tenant_id)


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_saved_connection(connection_id: int, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    ok = await service.delete_saved_connection(db, user.tenant_id, connection_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Connection not found")
    await log_audit(db, user.tenant_id, user.id, action="db_import_delete_connection", entity_type="db_connection", entity_id=connection_id)


# ---------------------------------------------------------------------------
# Schema / table / column discovery + sampling
# ---------------------------------------------------------------------------

async def _resolved_adapter(db: AsyncSession, tenant_id: int, connection: DbConnectionInput):
    try:
        params = await service.resolve_connection_params(db, tenant_id, connection)
    except service.DbImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not params.engine:
        raise HTTPException(status_code=400, detail="Call /test-connection first to resolve the database engine.")
    try:
        return service.build_adapter(params)
    except service.DbImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/schemas", response_model=SchemaListOut)
async def list_schemas(payload: DbConnectionInput, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    adapter = await _resolved_adapter(db, user.tenant_id, payload)
    try:
        schemas = await adapter.discover_schemas()
    except AdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        await adapter.close()
    return SchemaListOut(schemas=schemas)


@router.post("/{entity}/tables", response_model=list[TableOut])
async def list_tables(entity: str, payload: TableListRequest, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    try:
        target = service.get_entity(entity)
    except service.DbImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    adapter = await _resolved_adapter(db, user.tenant_id, payload.connection)
    try:
        tables = await adapter.discover_tables(payload.schema_name)
    except AdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        await adapter.close()
    ranked = service.recommend_tables(tables, target)
    return [
        TableOut(
            schema_name=t.schema, name=t.name, row_count_estimate=t.row_count_estimate,
            recommendation_score=t.recommendation_score, recommendation_reason=t.recommendation_reason,
        )
        for t in ranked
    ]


@router.post("/sample")
async def sample_table(payload: SampleRequest, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    adapter = await _resolved_adapter(db, user.tenant_id, payload.connection)
    try:
        rows = await adapter.sample_rows(payload.schema_name, payload.table, min(payload.limit, service.SAMPLE_ROW_LIMIT))
    except AdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        await adapter.close()
    return {"rows": rows}


# ---------------------------------------------------------------------------
# Map / validate / commit — reuses the exact same shared functions the CSV
# import endpoints use (core.ingestion.auto_map_columns / validate_records /
# resolve_commit_validation-equivalent gate), just fed from a live database
# read instead of an uploaded file.
# ---------------------------------------------------------------------------

@router.post("/{entity}/map", response_model=MappingResult)
async def map_table_columns(entity: str, payload: TableDetailRequest, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    try:
        target = service.get_entity(entity)
    except service.DbImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    adapter = await _resolved_adapter(db, user.tenant_id, payload.connection)
    try:
        columns = await adapter.discover_columns(payload.schema_name, payload.table)
    except AdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        await adapter.close()
    headers = [c.name for c in columns]
    mapping = auto_map_columns(headers, target.spec)
    return MappingResult(headers=headers, mapping=mapping, columns=[ColumnMeta(name=c.name, dtype=c.dtype, required=c.required, enum_values=c.enum_values) for c in target.spec.columns])


@router.post("/{entity}/validate", response_model=ValidationResult)
async def validate_table(
    entity: str,
    payload: TableValidateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    try:
        target = service.get_entity(entity)
    except service.DbImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    adapter = await _resolved_adapter(db, user.tenant_id, payload.connection)
    try:
        raw_rows = await adapter.read_rows(payload.schema_name, payload.table)
    except AdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        await adapter.close()

    if payload.mapping:
        rename = {uploaded: app_field for app_field, uploaded in payload.mapping.items() if uploaded}
        raw_rows = [{rename.get(k, k): v for k, v in row.items()} for row in raw_rows]

    return await validate_records(raw_rows, target.spec, db, user.tenant_id)


@router.post("/{entity}/commit")
async def commit_table_import(
    entity: str,
    payload: CommitRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    try:
        target = service.get_entity(entity)
    except service.DbImportError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    result = await validate_records(payload.edited_rows, target.spec, db, user.tenant_id)
    enforce_commit_gate(result, payload.skip_invalid)
    outcome = await target.commit_fn(db, user.tenant_id, result.valid_rows)
    created, updated = outcome if isinstance(outcome, tuple) else (outcome, 0)
    await touch_freshness(db, user.tenant_id, target.module)
    await log_audit(
        db, user.tenant_id, user.id, action=f"db_import_commit_{entity}", entity_type=entity,
        details=f"created={created} updated={updated} skipped={len(result.errors)} source=database",
    )
    return commit_response(result, created, updated)


# ---------------------------------------------------------------------------
# Local Connector registration/auth + job relay — what connector/ (the
# packaged application a customer installs, see connector/README.md)
# authenticates against, and how a tenant admin manages installs.
# ---------------------------------------------------------------------------

_CONNECTOR_DOWNLOAD_PATH = Path(__file__).resolve().parents[2] / "static" / "downloads" / "PlantwiseConnector.exe"


@router.get("/connectors/download")
async def download_connector(user=Depends(require_role("admin"))):
    if not _CONNECTOR_DOWNLOAD_PATH.exists():
        raise HTTPException(status_code=404, detail="The connector installer isn't available right now.")
    return FileResponse(
        _CONNECTOR_DOWNLOAD_PATH,
        media_type="application/octet-stream",
        filename="PlantwiseConnector.exe",
    )


@router.post("/connectors", response_model=ConnectorRegistrationKeyOut)
async def create_connector(payload: ConnectorCreateRequest, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    connector, registration_key = await connector_service.create_connector(db, user.tenant_id, user.id, payload.name)
    await log_audit(
        db, user.tenant_id, user.id, action="db_import_create_connector", entity_type="connector", entity_id=connector.id,
        details=f"name={connector.name}",
    )
    return ConnectorRegistrationKeyOut(connector_id=connector.id, name=connector.name, registration_key=registration_key)


@router.get("/connectors", response_model=list[ConnectorOut])
async def get_connectors(db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    return await connector_service.list_connectors(db, user.tenant_id)


@router.delete("/connectors/{connector_id}", status_code=204)
async def revoke_connector(connector_id: int, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    ok = await connector_service.revoke_connector(db, user.tenant_id, connector_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Connector not found")
    await log_audit(db, user.tenant_id, user.id, action="db_import_revoke_connector", entity_type="connector", entity_id=connector_id)


@router.post("/connectors/register", response_model=ConnectorTokenOut)
@limiter.limit("10/minute")
async def register_connector(payload: ConnectorRegisterRequest, db: AsyncSession = Depends(get_db), request: Request = None):
    """Called by the connector application itself, not a logged-in dashboard
    user — no require_role dependency, auth is the registration key itself.
    """
    try:
        connector, token = await connector_service.exchange_registration_key(db, payload.registration_key)
    except connector_service.ConnectorAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ConnectorTokenOut(connector_id=connector.id, connector_name=connector.name, connector_token=token)


# --- Dashboard side: enqueue a job for a connector, poll for its result ---

@router.post("/connectors/{connector_id}/jobs", response_model=ConnectorJobOut)
async def create_connector_job(
    connector_id: int, payload: ConnectorJobCreateRequest, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))
):
    try:
        job = await connector_service.create_job(db, user.tenant_id, user.id, connector_id, payload.action, payload.params)
    except connector_service.ConnectorJobError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return job


@router.get("/connectors/{connector_id}/jobs/{job_id}", response_model=ConnectorJobOut)
async def get_connector_job(connector_id: int, job_id: int, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    job = await connector_service.get_job(db, user.tenant_id, job_id)
    if job is None or job.connector_id != connector_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# --- Connector side: poll for work, report back. Bearer-authenticated with
# the connector's own token (get_current_connector), not a dashboard user. ---

@router.get("/connector/jobs/next", response_model=ConnectorJobOut | None)
async def poll_next_job(db: AsyncSession = Depends(get_db), connector: ConnectorRegistration = Depends(get_current_connector)):
    return await connector_service.claim_next_job(db, connector)


@router.post("/connector/jobs/{job_id}/result", response_model=ConnectorJobOut)
async def submit_job_result(
    job_id: int,
    payload: ConnectorJobResultRequest,
    db: AsyncSession = Depends(get_db),
    connector: ConnectorRegistration = Depends(get_current_connector),
):
    try:
        return await connector_service.submit_job_result(db, connector, job_id, payload.status, payload.result, payload.error)
    except connector_service.ConnectorJobError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Continuous sync — a saved mapping re-run on a timer by the scheduler
# instead of once by hand (see app/core/scheduler.py:_run_due_syncs and
# service.run_sync). Customers who never set one of these up keep using
# manual entry / CSV upload exactly as before — this is additive.
# ---------------------------------------------------------------------------

@router.post("/sync-schedules", response_model=SyncScheduleOut)
async def create_sync_schedule(
    payload: SyncScheduleCreateRequest, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))
):
    try:
        schedule = await service.create_sync_schedule(
            db, user.tenant_id, user.id,
            entity=payload.entity,
            connection_id=payload.connection_id,
            connector_id=payload.connector_id,
            schema_name=payload.schema_name,
            table_name=payload.table,
            column_mapping=payload.column_mapping,
            watermark_column=payload.watermark_column,
            interval_minutes=payload.interval_minutes,
        )
    except (service.DbImportError, service.SyncError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        db, user.tenant_id, user.id, action="db_import_create_sync_schedule", entity_type="sync_schedule",
        entity_id=schedule.id, details=f"entity={payload.entity} table={payload.table}",
    )
    return schedule


@router.get("/sync-schedules", response_model=list[SyncScheduleOut])
async def get_sync_schedules(db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    return await service.list_sync_schedules(db, user.tenant_id)


@router.patch("/sync-schedules/{schedule_id}", response_model=SyncScheduleOut)
async def update_sync_schedule(
    schedule_id: int, payload: SyncScheduleUpdateRequest, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))
):
    schedule = await service.set_sync_schedule_enabled(db, user.tenant_id, schedule_id, payload.enabled)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Sync schedule not found")
    await log_audit(
        db, user.tenant_id, user.id, action="db_import_update_sync_schedule", entity_type="sync_schedule",
        entity_id=schedule_id, details=f"enabled={payload.enabled}",
    )
    return schedule


@router.delete("/sync-schedules/{schedule_id}", status_code=204)
async def remove_sync_schedule(schedule_id: int, db: AsyncSession = Depends(get_db), user=Depends(require_role("admin"))):
    ok = await service.delete_sync_schedule(db, user.tenant_id, schedule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Sync schedule not found")
    await log_audit(db, user.tenant_id, user.id, action="db_import_delete_sync_schedule", entity_type="sync_schedule", entity_id=schedule_id)


register_module(
    ModuleRegistration(
        key="db_import",
        prefix="db-import",
        router=router,
        get_summary=None,
        get_shift_contribution=None,
    )
)
