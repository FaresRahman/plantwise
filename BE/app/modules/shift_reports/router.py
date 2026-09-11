import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.contracts import ChatToolSpec, register_tool
from app.core.db import get_db
from app.core.deps import get_tenant_id, require_role
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
from app.core.schema_context import ColumnDoc, QueryableModel, register_queryable_model
from app.modules.shift_reports import service
from app.modules.shift_reports.models import ShiftReport, ShiftSchedule
from app.modules.shift_reports.schemas import (
    GenerateReportRequest,
    ShiftReportOut,
    ShiftReportQueryArgs,
    ShiftScheduleIn,
    ShiftScheduleOut,
)

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "shift_reports", "status": "ok"}


# ---------------------------------------------------------------------------
# Shift schedule config CSV
# ---------------------------------------------------------------------------

SHIFT_SCHEDULE_TEMPLATE_HEADER = "name,start_time,end_time,areas,recipients\n"


@router.get("/csv/schedules/template")
async def schedule_csv_template(_tenant_id: int = Depends(get_tenant_id)):
    return Response(content=SHIFT_SCHEDULE_TEMPLATE_HEADER, media_type="text/csv")


@router.post("/csv/schedules/map")
async def map_schedule_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", service.SHIFT_SCHEDULE_CSV_SPEC)


@router.post("/csv/schedules/validate")
async def validate_schedule_csv(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role("admin")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", service.SHIFT_SCHEDULE_CSV_SPEC, db, tenant_id, column_mapping=column_mapping)


@router.post("/csv/schedules/commit")
async def commit_schedule_csv(
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
    result = await resolve_commit_validation(service.SHIFT_SCHEDULE_CSV_SPEC, db, user.tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)
    created, _ = await service.commit_shift_schedules_config(db, user.tenant_id, result.valid_rows)
    await touch_freshness(db, user.tenant_id, "shift_reports")
    await log_audit(
        db, user.tenant_id, user.id, action="commit_shift_schedules_config", entity_type="shift_schedule",
        details=f"created={created} skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )
    return commit_response(result, created)


@router.post("/schedules", response_model=ShiftScheduleOut, status_code=201)
async def create_schedule(
    payload: ShiftScheduleIn,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    schedule = await service.create_schedule(db, tenant_id, payload)
    await log_audit(
        db, tenant_id, user.id, action="create_shift_schedule", entity_type="shift_schedule", entity_id=schedule.id
    )
    return schedule


@router.get("/schedules", response_model=list[ShiftScheduleOut])
async def list_schedules(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_tenant_id)):
    return await service.list_schedules(db, tenant_id)


@router.put("/schedules/{schedule_id}", response_model=ShiftScheduleOut)
async def update_schedule(
    schedule_id: int,
    payload: ShiftScheduleIn,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    try:
        schedule = await service.update_schedule(db, tenant_id, schedule_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await log_audit(
        db, tenant_id, user.id, action="update_shift_schedule", entity_type="shift_schedule", entity_id=schedule_id
    )
    return schedule


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    try:
        await service.delete_schedule(db, tenant_id, schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await log_audit(
        db, tenant_id, user.id, action="delete_shift_schedule", entity_type="shift_schedule", entity_id=schedule_id
    )
    return None


@router.post("/generate", response_model=ShiftReportOut)
async def generate(
    payload: GenerateReportRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin", "operator")),
):
    try:
        return await service.generate_report(
            db, tenant_id, payload.shift_schedule_id, payload.window_start, payload.window_end
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=list[ShiftReportOut])
async def list_reports(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_tenant_id)):
    return await service.list_reports(db, tenant_id)


@router.get("/{report_id}", response_model=ShiftReportOut)
async def get_report(
    report_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_tenant_id)
):
    try:
        return await service.get_report(db, tenant_id, report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{report_id}/export")
async def export_report(
    report_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_tenant_id)
):
    try:
        report = await service.get_report(db, tenant_id, report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    schedule_name = None
    if report.shift_schedule_id is not None:
        # Explicit tenant filter (not a bare db.get by id) — defense-in-depth
        # so this can never leak another tenant's schedule name even if a
        # future code path ever populates shift_schedule_id from a looser
        # source than today's tenant-scoped write path.
        schedule = await db.scalar(
            select(ShiftSchedule).where(
                ShiftSchedule.tenant_id == tenant_id, ShiftSchedule.id == report.shift_schedule_id
            )
        )
        schedule_name = schedule.name if schedule else None

    text = service.render_report_text(report, schedule_name)
    filename = f"shift-report-{report.window_start.strftime('%Y%m%d-%H%M')}.txt"
    return Response(
        content=text, media_type="text/plain", headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


register_tool(
    ChatToolSpec(
        name="shift_reports_query",
        description=(
            "Looks up past shift reports for this tenant, optionally filtered by shift schedule name "
            "(e.g. 'Day Shift') and limited to the most recent N. Returns each report's time window, its "
            "per-module summary (production/quality/maintenance/inventory) — use this to actually answer "
            "'summarize the last shift' — and its next-shift actions. If schedule_name doesn't match a "
            "known schedule, returns found=False or asks for clarification — never guesses which schedule "
            "was meant."
        ),
        args_schema=ShiftReportQueryArgs,
        fn=service.shift_reports_query_tool,
    )
)

register_queryable_model(
    "shift_reports",
    QueryableModel(
        model=ShiftReport,
        description="A compiled handover report for one shift's time window.",
        columns=[
            ColumnDoc("window_start", "start of the shift window this report covers"),
            ColumnDoc("window_end", "end of the shift window this report covers"),
            ColumnDoc("compiled_content", "JSON list of per-module handover summaries (production/quality/maintenance/inventory)"),
            ColumnDoc("next_shift_actions", "JSON list of explicit handover actions for the next shift"),
        ],
        examples=[
            "Question: What happened on the Day Shift's last report? -> {schedule_name: 'Day Shift', limit: 1}",
        ],
    ),
)

register_module(
    ModuleRegistration(
        key="shift_reports",
        prefix="shift-reports",
        router=router,
        get_summary=service.get_summary,
        get_shift_contribution=None,  # shift reports don't contribute to themselves
    )
)
