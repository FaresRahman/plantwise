import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.core.audit import log_audit
from app.modules.quality import service
from app.modules.quality.models import InspectionRecord
from app.modules.quality.schemas import (
    CharacteristicIn,
    CharacteristicOut,
    CharacteristicTrendOut,
    InspectionQuickIn,
    InspectionRecordOut,
    QualityHoldIn,
    QualityHoldOut,
    QualityHoldRelease,
)

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "quality", "status": "ok"}


# ---------------------------------------------------------------------------
# Characteristic config
# ---------------------------------------------------------------------------

@router.get("/characteristics", response_model=list[CharacteristicOut])
async def get_characteristics(
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_characteristics(db, tenant_id)


@router.post("/characteristics", response_model=CharacteristicOut, status_code=201)
async def create_characteristic(
    payload: CharacteristicIn,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    char = await service.create_characteristic(db, tenant_id, payload)
    await log_audit(
        db, tenant_id, user.id, action="create_characteristic", entity_type="characteristic", entity_id=char.id,
        details=f"{char.part_id}/{char.characteristic_name}",
    )
    return char


@router.put("/characteristics/{characteristic_id}", response_model=CharacteristicOut)
async def update_characteristic(
    characteristic_id: int,
    payload: CharacteristicIn,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    char = await service.update_characteristic(db, tenant_id, characteristic_id, payload)
    if char is None:
        raise HTTPException(status_code=404, detail="Characteristic not found")
    await log_audit(
        db, tenant_id, user.id, action="update_characteristic", entity_type="characteristic", entity_id=char.id,
        details=f"{char.part_id}/{char.characteristic_name}",
    )
    return char


@router.delete("/characteristics/{characteristic_id}", status_code=204)
async def delete_characteristic(
    characteristic_id: int,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    ok = await service.delete_characteristic(db, tenant_id, characteristic_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Characteristic not found")
    await log_audit(
        db, tenant_id, user.id, action="delete_characteristic", entity_type="characteristic", entity_id=characteristic_id,
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Characteristic config CSV
# ---------------------------------------------------------------------------

CHARACTERISTIC_TEMPLATE_HEADER = (
    "part_id,characteristic_name,nominal_value,tolerance,inspection_type,line_id,station_id,defect_categories\n"
)


@router.get("/csv/characteristics/template")
async def characteristic_csv_template(_tenant_id: int = Depends(get_tenant_id)):
    return Response(content=CHARACTERISTIC_TEMPLATE_HEADER, media_type="text/csv")


@router.post("/csv/characteristics/map")
async def map_characteristic_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", service.CHARACTERISTIC_CSV_SPEC)


@router.post("/csv/characteristics/validate")
async def validate_characteristic_csv(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role("admin")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", service.CHARACTERISTIC_CSV_SPEC, db, tenant_id, column_mapping=column_mapping)


@router.post("/csv/characteristics/commit")
async def commit_characteristic_csv(
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
    result = await resolve_commit_validation(service.CHARACTERISTIC_CSV_SPEC, db, user.tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)
    created, updated = await service.commit_characteristics_config(db, user.tenant_id, result.valid_rows)
    await touch_freshness(db, user.tenant_id, "quality")
    await log_audit(
        db, user.tenant_id, user.id, action="commit_characteristics_config", entity_type="characteristic",
        details=f"created={created} updated={updated} skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )
    return commit_response(result, created, updated)


@router.post("/load-sample-data")
async def load_sample_data(
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    result = await service.load_sample_data(db, tenant_id, user.id)
    await log_audit(db, tenant_id, user.id, action="load_sample_data", entity_type="quality", details=str(result))
    return result


@router.get("/characteristics/{characteristic_id}/trend", response_model=CharacteristicTrendOut)
async def get_characteristic_trend(
    characteristic_id: int,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    char = await service.get_characteristic(db, tenant_id, characteristic_id)
    if char is None:
        raise HTTPException(status_code=404, detail="Characteristic not found")
    trend = await service.get_characteristic_trend(db, tenant_id, char)
    return CharacteristicTrendOut(
        characteristic_id=char.id,
        part_id=char.part_id,
        characteristic_name=char.characteristic_name,
        **trend,
    )


@router.get("/characteristics/{characteristic_id}/measurements")
async def get_characteristic_measurements(
    characteristic_id: int,
    days: int = 30,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    char = await service.get_characteristic(db, tenant_id, characteristic_id)
    if char is None:
        raise HTTPException(status_code=404, detail="Characteristic not found")
    return await service.get_recent_measurements(db, tenant_id, char, days=min(max(days, 1), 365))


@router.post("/characteristics/{characteristic_id}/inspections/quick", response_model=InspectionRecordOut, status_code=201)
async def quick_log_inspection(
    characteristic_id: int,
    payload: InspectionQuickIn,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    """Single-row alternative to the inspection-records CSV, for logging one
    inspection result without building a CSV for a single row (PRD §4.9).
    """
    char = await service.get_characteristic(db, tenant_id, characteristic_id)
    if char is None:
        raise HTTPException(status_code=404, detail="Characteristic not found")

    record = InspectionRecord(
        tenant_id=tenant_id,
        part_id=char.part_id,
        timestamp=payload.timestamp or datetime.utcnow(),
        characteristic_name=char.characteristic_name,
        measured_value=payload.measured_value,
        pass_fail=payload.pass_fail,
        defect_type=payload.defect_type,
        line_id=char.line_id,
        station_id=payload.station_id or char.station_id,
        inspector=payload.inspector,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    await touch_freshness(db, tenant_id, "quality")
    await service.check_and_alert_spikes(db, tenant_id, {(char.part_id, char.characteristic_name, char.line_id)})
    await log_audit(
        db, tenant_id, user.id, action="quick_log_inspection", entity_type="inspection_record", entity_id=record.id,
        details=f"{char.part_id}/{char.characteristic_name}",
    )
    return record


# ---------------------------------------------------------------------------
# CSV ingestion — inspection records
# ---------------------------------------------------------------------------

@router.get("/csv/inspection-records/template")
async def inspection_records_template(user=Depends(get_current_user)):
    return Response(
        content=service.INSPECTION_RECORD_CSV_HEADER + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inspection-records-template.csv"},
    )


@router.post("/csv/inspection-records/map")
async def map_inspection_records_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", service.INSPECTION_RECORD_CSV_SPEC)


@router.post("/csv/inspection-records/validate", response_model=ValidationResult)
async def inspection_records_validate(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", service.INSPECTION_RECORD_CSV_SPEC, db, tenant_id, column_mapping=column_mapping)


@router.post("/csv/inspection-records/commit")
async def inspection_records_commit(
    file: UploadFile | None = File(None),
    edited_rows: str | None = Form(None),
    mapping: str | None = Form(None),
    skip_invalid: bool = Form(False),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    if file is not None:
        await enforce_upload_limit(file)
    column_mapping = json.loads(mapping) if mapping else None
    result = await resolve_commit_validation(service.INSPECTION_RECORD_CSV_SPEC, db, tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)
    committed, touched = await service.commit_inspection_rows(db, tenant_id, result.valid_rows)
    await touch_freshness(db, tenant_id, "quality")
    await service.check_and_alert_spikes(db, tenant_id, touched)
    await log_audit(
        db, tenant_id, user.id, action="commit_inspection_records", entity_type="inspection_record",
        details=f"rows_committed={committed} rows_skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )
    return commit_response(result, committed)


# ---------------------------------------------------------------------------
# Quality holds (lot/batch quarantine) — PRD §4.6 shift-report requirement
# ---------------------------------------------------------------------------

@router.get("/holds", response_model=list[QualityHoldOut])
async def get_holds(
    hold_status: str | None = None,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_holds(db, tenant_id, status=hold_status)


@router.post("/holds", response_model=QualityHoldOut, status_code=201)
async def create_hold(
    payload: QualityHoldIn,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    hold = await service.create_hold(db, tenant_id, user.id, payload)
    await log_audit(
        db, tenant_id, user.id, action="create_quality_hold", entity_type="quality_hold", entity_id=hold.id,
        details=f"{hold.part_id}/lot {hold.lot_number}: {hold.reason}",
    )
    return hold


@router.post("/holds/{hold_id}/release", response_model=QualityHoldOut)
async def release_hold(
    hold_id: int,
    payload: QualityHoldRelease,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    try:
        hold = await service.release_hold(db, tenant_id, user.id, hold_id, payload.release_note)
    except service.ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if hold is None:
        raise HTTPException(status_code=404, detail="Hold not found")
    await log_audit(
        db, tenant_id, user.id, action="release_quality_hold", entity_type="quality_hold", entity_id=hold.id,
        details=hold.release_note,
    )
    return hold


register_module(
    ModuleRegistration(
        key="quality",
        prefix="quality",
        router=router,
        get_summary=service.get_summary,
        get_shift_contribution=service.get_shift_contribution,
    )
)
