import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.db import get_db
from app.core.deps import get_current_user, get_tenant_id, require_role
from app.core.ingestion import (
    ValidationResult,
    commit_response,
    enforce_commit_gate,
    map_csv_columns,
    resolve_commit_validation,
    touch_freshness,
    validate_csv,
)
from app.core.upload_limits import enforce_upload_limit
from app.core.module_registry import ModuleRegistration, register_module
from app.modules.production import engine, service
from app.modules.production.models import RUN_STATES, OutputLog
from app.modules.production.schemas import LineCreate, LineOut, LineUpdate, OutputLogOut, OutputLogQuickIn
from app.modules.production.service import OUTPUT_LOG_CSV_HEADER, OUTPUT_LOG_CSV_SPEC

router = APIRouter()


def _default_window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    if start is None or end is None:
        return service.today_window()
    return start, end


@router.get("/health")
async def health():
    return {"module": "production", "status": "ok"}


# ---------------------------------------------------------------------------
# Line config CRUD
# ---------------------------------------------------------------------------


@router.get("/lines", response_model=list[LineOut])
async def get_lines(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    return await service.list_lines(db, tenant_id)


@router.post("/lines", response_model=LineOut, status_code=status.HTTP_201_CREATED)
async def create_line(
    payload: LineCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    try:
        line = await service.create_line(db, tenant_id, payload)
    except service.DuplicateLineCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        db, tenant_id, user.id, action="create_line", entity_type="line", entity_id=line.id,
        details=f"line_code={line.line_code}",
    )
    return line


@router.put("/lines/{line_id}", response_model=LineOut)
async def update_line(
    line_id: int,
    payload: LineUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    try:
        line = await service.update_line(db, tenant_id, line_id, payload)
    except service.DuplicateLineCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not line:
        raise HTTPException(status_code=404, detail="line not found")
    await log_audit(db, tenant_id, user.id, action="update_line", entity_type="line", entity_id=line.id)
    return line


@router.delete("/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_line(
    line_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    try:
        ok = await service.delete_line(db, tenant_id, line_id)
    except service.LineHasOutputLogsError:
        raise HTTPException(status_code=409, detail="cannot delete a line with existing output-log history")
    if not ok:
        raise HTTPException(status_code=404, detail="line not found")
    await log_audit(db, tenant_id, user.id, action="delete_line", entity_type="line", entity_id=line_id)
    return None


# ---------------------------------------------------------------------------
# Line config CSV
# ---------------------------------------------------------------------------

LINE_TEMPLATE_HEADER = "line_code,name,stations,products,shift_target_units,ideal_cycle_time_seconds\n"


@router.get("/csv/lines/template")
async def line_csv_template(_tenant_id: int = Depends(get_tenant_id)):
    return Response(content=LINE_TEMPLATE_HEADER, media_type="text/csv")


@router.post("/csv/lines/map")
async def map_line_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", service.LINE_CSV_SPEC)


@router.post("/csv/lines/validate")
async def validate_line_csv(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role("admin")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", service.LINE_CSV_SPEC, db, tenant_id, column_mapping=column_mapping)


@router.post("/csv/lines/commit")
async def commit_line_csv(
    file: UploadFile | None = File(None),
    edited_rows: str | None = Form(None),
    mapping: str | None = Form(None),
    skip_invalid: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    if file is not None:
        await enforce_upload_limit(file)
    column_mapping = json.loads(mapping) if mapping else None
    result = await resolve_commit_validation(service.LINE_CSV_SPEC, db, user.tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)
    created, updated = await service.commit_lines_config(db, user.tenant_id, result.valid_rows)
    await touch_freshness(db, user.tenant_id, "production")
    await log_audit(
        db, user.tenant_id, user.id, action="commit_lines_config", entity_type="line",
        details=f"created={created} updated={updated} skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )
    return commit_response(result, created, updated)


@router.post("/lines/{line_id}/output-logs/quick", response_model=OutputLogOut, status_code=status.HTTP_201_CREATED)
async def quick_log_output(
    line_id: int,
    payload: OutputLogQuickIn,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin", "operator")),
):
    """Single-row alternative to the output-logs CSV, for logging one shift's/
    station's numbers without building a CSV for a single row (PRD §4.9).
    """
    line = await service.get_line(db, tenant_id, line_id)
    if not line:
        raise HTTPException(status_code=404, detail="line not found")
    if payload.station_id not in line.stations:
        raise HTTPException(
            status_code=400,
            detail=f"station '{payload.station_id}' is not registered on this line (known stations: {', '.join(line.stations) or 'none'})",
        )
    if payload.run_state not in RUN_STATES:
        raise HTTPException(status_code=400, detail=f"run_state must be one of {RUN_STATES}")

    log = OutputLog(
        tenant_id=tenant_id,
        line_id=line.id,
        station_id=payload.station_id,
        timestamp=payload.timestamp or datetime.utcnow(),
        units_produced=payload.units_produced,
        units_good=payload.units_good,
        units_reject=payload.units_reject,
        run_state=payload.run_state,
        downtime_minutes=payload.downtime_minutes,
        downtime_reason=payload.downtime_reason,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    await touch_freshness(db, tenant_id, "production")
    await log_audit(
        db, tenant_id, user.id, action="quick_log_output", entity_type="output_log", entity_id=log.id,
        details=f"line={line.line_code} station={payload.station_id}",
    )
    return log


@router.post("/load-sample-data")
async def load_sample_data(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    result = await service.load_sample_data(db, tenant_id, user.id)
    await log_audit(db, tenant_id, user.id, action="load_sample_data", entity_type="production", details=str(result))
    return result


# ---------------------------------------------------------------------------
# Compute / drill-down
# ---------------------------------------------------------------------------


@router.get("/lines/{line_id}/metrics")
async def get_line_metrics(
    line_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(get_current_user),
):
    start, end = _default_window(start, end)
    result = await engine.compute_line_metrics(db, tenant_id, line_id, start, end)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/lines/{line_id}/oee-history")
async def get_line_oee_history(
    line_id: int,
    days: int = 14,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(get_current_user),
):
    days = min(max(days, 1), 90)
    _, end = _default_window(None, None)
    history = await engine.compute_oee_history(db, tenant_id, line_id, days, end)
    if not history:
        raise HTTPException(status_code=404, detail="line not found")
    return history


@router.get("/lines/{line_id}/downtime-events")
async def get_line_downtime_events(
    line_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(get_current_user),
):
    line = await service.get_line(db, tenant_id, line_id)
    if not line:
        raise HTTPException(status_code=404, detail="line not found")
    start, end = _default_window(start, end)
    return await engine.get_downtime_events(db, tenant_id, line.line_code, start, end)


# ---------------------------------------------------------------------------
# CSV ingestion — output logs
# ---------------------------------------------------------------------------


@router.get("/csv/output-logs/template")
async def output_logs_template(user=Depends(get_current_user)):
    return Response(content=OUTPUT_LOG_CSV_HEADER + "\n", media_type="text/csv")


@router.post("/csv/output-logs/map")
async def map_output_logs_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", OUTPUT_LOG_CSV_SPEC)


@router.post("/csv/output-logs/validate", response_model=ValidationResult)
async def validate_output_logs(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", OUTPUT_LOG_CSV_SPEC, db, tenant_id, column_mapping=column_mapping)


@router.post("/csv/output-logs/commit")
async def commit_output_logs(
    file: UploadFile | None = File(None),
    edited_rows: str | None = Form(None),
    mapping: str | None = Form(None),
    skip_invalid: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin", "operator")),
):
    if file is not None:
        await enforce_upload_limit(file)
    column_mapping = json.loads(mapping) if mapping else None
    result = await resolve_commit_validation(OUTPUT_LOG_CSV_SPEC, db, tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)

    committed = await service.commit_output_log_rows(db, tenant_id, result.valid_rows)
    await log_audit(
        db, tenant_id, user.id, action="commit_output_logs", entity_type="output_log",
        details=f"rows_committed={committed} rows_skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )
    return commit_response(result, committed)


register_module(
    ModuleRegistration(
        key="production",
        prefix="production",
        router=router,
        get_summary=service.get_summary,
        get_shift_contribution=service.get_shift_contribution,
    )
)
