import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.db import get_db
from app.core.deps import get_tenant_id, require_role
from app.core.ingestion import (
    commit_response,
    enforce_commit_gate,
    map_csv_columns,
    resolve_commit_validation,
    touch_freshness,
    validate_csv,
)
from app.core.upload_limits import enforce_upload_limit
from app.core.module_registry import ModuleRegistration, register_module
from app.modules.predictive_maintenance import service
from app.modules.predictive_maintenance.engine import recompute_all
from app.modules.predictive_maintenance.models import MaintenanceHistory, SensorReading
from app.modules.predictive_maintenance.schemas import (
    ActionRequest,
    AssetIn,
    AssetOut,
    AssetUpdate,
    MaintenanceHistoryOut,
    MaintenanceHistoryQuickIn,
    MaintenanceHistoryUpdateIn,
    MetricRangeQuickIn,
    ReadingOut,
    ReadingQuickIn,
    ReadingsSeriesOut,
    ReadingUpdateIn,
    RecommendationOut,
)

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "predictive_maintenance", "status": "ok"}


# ---------------------------------------------------------------------------
# Asset registry
# ---------------------------------------------------------------------------

@router.get("/assets", response_model=list[AssetOut])
async def list_assets(tenant_id: int = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    return await service.list_assets(db, tenant_id)


@router.post("/assets", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def create_asset(
    payload: AssetIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    try:
        asset = await service.create_asset(db, user.tenant_id, payload)
    except service.ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(
        db, user.tenant_id, user.id, action="create_asset", entity_type="asset", entity_id=asset.id,
        details=f"asset_code={asset.asset_code}",
    )
    return asset


@router.put("/assets/{asset_id}", response_model=AssetOut)
async def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    asset = await service.update_asset(db, user.tenant_id, asset_id, payload)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    await log_audit(
        db, user.tenant_id, user.id, action="update_asset", entity_type="asset", entity_id=asset.id,
        details=f"fields={list(payload.model_dump(exclude_unset=True).keys())}",
    )
    return asset


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    deleted = await service.delete_asset(db, user.tenant_id, asset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Asset not found")
    await log_audit(db, user.tenant_id, user.id, action="delete_asset", entity_type="asset", entity_id=asset_id)


@router.get("/assets/{asset_id}/readings", response_model=ReadingsSeriesOut)
async def get_asset_readings(
    asset_id: int,
    metric: str = Query(...),
    days: int = Query(30, ge=1, le=365),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    asset = await service.get_asset(db, tenant_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return await service.get_asset_readings(db, tenant_id, asset_id, metric, days)


@router.get("/assets/{asset_id}/maintenance-history", response_model=list[MaintenanceHistoryOut])
async def get_asset_maintenance_history(
    asset_id: int,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    asset = await service.get_asset(db, tenant_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return await service.list_maintenance_history(db, tenant_id, asset_id)


@router.post("/assets/{asset_id}/readings/quick", response_model=ReadingOut, status_code=status.HTTP_201_CREATED)
async def quick_log_reading(
    asset_id: int,
    payload: ReadingQuickIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    """Single-row alternative to the sensor-readings CSV, for logging one
    reading without building a CSV for a single row (PRD §4.9).
    """
    asset = await service.get_asset(db, user.tenant_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    reading = SensorReading(
        tenant_id=user.tenant_id,
        asset_id=asset.id,
        timestamp=payload.timestamp or datetime.utcnow(),
        metric=payload.metric,
        value=payload.value,
        unit=payload.unit,
    )
    db.add(reading)
    await db.commit()
    await db.refresh(reading)
    await touch_freshness(db, user.tenant_id, "predictive_maintenance")
    await recompute_all(db, user.tenant_id)
    await log_audit(
        db, user.tenant_id, user.id, action="quick_log_reading", entity_type="sensor_reading", entity_id=reading.id,
        details=f"asset={asset.asset_code} metric={payload.metric}",
    )
    return reading


@router.post("/assets/{asset_id}/maintenance-history/quick", response_model=MaintenanceHistoryOut, status_code=status.HTTP_201_CREATED)
async def quick_log_maintenance(
    asset_id: int,
    payload: MaintenanceHistoryQuickIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    """Single-row alternative to the maintenance-history CSV, for logging one
    service event (e.g. right after fixing something) without building a CSV.
    """
    from app.modules.predictive_maintenance.engine import capture_failure_signatures

    asset = await service.get_asset(db, user.tenant_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    event_date = payload.event_date or datetime.utcnow().date()
    record = MaintenanceHistory(
        tenant_id=user.tenant_id,
        asset_id=asset.id,
        date=event_date,
        type=payload.type,
        description=payload.description,
        downtime_hours=payload.downtime_hours,
        parts_replaced=payload.parts_replaced,
    )
    db.add(record)
    await db.flush()

    if payload.type == "corrective":
        await capture_failure_signatures(db, user.tenant_id, asset, record.id, event_date)

    await db.commit()
    await db.refresh(record)
    await touch_freshness(db, user.tenant_id, "predictive_maintenance")
    await recompute_all(db, user.tenant_id)
    await log_audit(
        db, user.tenant_id, user.id, action="quick_log_maintenance", entity_type="maintenance_history", entity_id=record.id,
        details=f"asset={asset.asset_code} type={payload.type}",
    )
    return record


@router.patch("/assets/{asset_id}/readings/{reading_id}", response_model=ReadingOut)
async def update_reading(
    asset_id: int,
    reading_id: int,
    payload: ReadingUpdateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    reading = await service.update_reading(db, user.tenant_id, asset_id, reading_id, payload)
    if reading is None:
        raise HTTPException(status_code=404, detail="Reading not found")
    await recompute_all(db, user.tenant_id)
    await log_audit(db, user.tenant_id, user.id, action="update_reading", entity_type="sensor_reading", entity_id=reading.id)
    return reading


@router.delete("/assets/{asset_id}/readings/{reading_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reading(
    asset_id: int,
    reading_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    deleted = await service.delete_reading(db, user.tenant_id, asset_id, reading_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Reading not found")
    await recompute_all(db, user.tenant_id)
    await log_audit(db, user.tenant_id, user.id, action="delete_reading", entity_type="sensor_reading", entity_id=reading_id)


@router.patch("/assets/{asset_id}/maintenance-history/{record_id}", response_model=MaintenanceHistoryOut)
async def update_maintenance_record(
    asset_id: int,
    record_id: int,
    payload: MaintenanceHistoryUpdateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    record = await service.update_maintenance_record(db, user.tenant_id, asset_id, record_id, payload)
    if record is None:
        raise HTTPException(status_code=404, detail="Maintenance record not found")
    await log_audit(db, user.tenant_id, user.id, action="update_maintenance", entity_type="maintenance_history", entity_id=record.id)
    return record


@router.delete("/assets/{asset_id}/maintenance-history/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_maintenance_record(
    asset_id: int,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    deleted = await service.delete_maintenance_record(db, user.tenant_id, asset_id, record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Maintenance record not found")
    await log_audit(db, user.tenant_id, user.id, action="delete_maintenance", entity_type="maintenance_history", entity_id=record_id)


@router.post("/assets/{asset_id}/metric-ranges/quick", response_model=AssetOut)
async def quick_set_metric_range(
    asset_id: int,
    payload: MetricRangeQuickIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    """Single-row alternative to the asset-metric-ranges CSV/DB sync — sets
    (or replaces) one metric's normal range on this asset without building a
    CSV for one row.
    """
    asset = await service.get_asset(db, user.tenant_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    metrics = dict(asset.monitored_metrics or {})
    metrics[payload.metric_name] = {"min": payload.min, "max": payload.max, "unit": payload.unit or ""}
    asset.monitored_metrics = metrics  # reassign, not in-place mutate — SQLAlchemy only detects JSON changes this way
    await db.commit()
    await db.refresh(asset)
    await touch_freshness(db, user.tenant_id, "predictive_maintenance")
    await recompute_all(db, user.tenant_id)
    await log_audit(
        db, user.tenant_id, user.id, action="quick_set_metric_range", entity_type="asset", entity_id=asset.id,
        details=f"asset={asset.asset_code} metric={payload.metric_name} min={payload.min} max={payload.max}",
    )
    return asset


# ---------------------------------------------------------------------------
# Asset config CSV
# ---------------------------------------------------------------------------

ASSET_TEMPLATE_HEADER = "asset_code,name,category,line_area,criticality,install_date\n"


@router.get("/csv/assets/template")
async def asset_csv_template(_tenant_id: int = Depends(get_tenant_id)):
    return Response(content=ASSET_TEMPLATE_HEADER, media_type="text/csv")


@router.post("/csv/assets/map")
async def map_asset_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", service.ASSET_CSV_SPEC)


@router.post("/csv/assets/validate")
async def validate_asset_csv(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role("admin")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", service.ASSET_CSV_SPEC, db, tenant_id, column_mapping=column_mapping)


@router.post("/csv/assets/commit")
async def commit_asset_csv(
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
    result = await resolve_commit_validation(service.ASSET_CSV_SPEC, db, user.tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)
    created, updated = await service.commit_assets_config(db, user.tenant_id, result.valid_rows)
    await touch_freshness(db, user.tenant_id, "predictive_maintenance")
    await log_audit(
        db, user.tenant_id, user.id, action="commit_assets_config", entity_type="asset",
        details=f"created={created} updated={updated} skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )
    return commit_response(result, created, updated)


# ---------------------------------------------------------------------------
# Sensor readings CSV
# ---------------------------------------------------------------------------

READINGS_TEMPLATE_HEADER = "asset_id,timestamp,metric,value,unit\n"
MAINTENANCE_TEMPLATE_HEADER = "asset_id,date,type,description,downtime_hours,parts_replaced\n"


@router.get("/csv/readings/template")
async def readings_csv_template(_tenant_id: int = Depends(get_tenant_id)):
    return Response(content=READINGS_TEMPLATE_HEADER, media_type="text/csv")


@router.post("/csv/readings/map")
async def map_readings_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", service.READINGS_CSV_SPEC)


@router.post("/csv/readings/validate")
async def validate_readings_csv(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", service.READINGS_CSV_SPEC, db, tenant_id, column_mapping=column_mapping)


@router.post("/csv/readings/commit")
async def commit_readings_csv(
    file: UploadFile | None = File(None),
    edited_rows: str | None = Form(None),
    mapping: str | None = Form(None),
    skip_invalid: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    if file is not None:
        await enforce_upload_limit(file)
    column_mapping = json.loads(mapping) if mapping else None
    result = await resolve_commit_validation(service.READINGS_CSV_SPEC, db, user.tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)
    committed = await service.commit_readings(db, user.tenant_id, result.valid_rows)
    await touch_freshness(db, user.tenant_id, "predictive_maintenance")
    await recompute_all(db, user.tenant_id)
    await log_audit(
        db, user.tenant_id, user.id, action="commit_sensor_readings", entity_type="sensor_reading",
        details=f"rows_committed={committed} rows_skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )
    return commit_response(result, committed)


# ---------------------------------------------------------------------------
# Maintenance history CSV
# ---------------------------------------------------------------------------

@router.get("/csv/maintenance-history/template")
async def maintenance_csv_template(_tenant_id: int = Depends(get_tenant_id)):
    return Response(content=MAINTENANCE_TEMPLATE_HEADER, media_type="text/csv")


@router.post("/csv/maintenance-history/map")
async def map_maintenance_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", service.MAINTENANCE_CSV_SPEC)


@router.post("/csv/maintenance-history/validate")
async def validate_maintenance_csv(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", service.MAINTENANCE_CSV_SPEC, db, tenant_id, column_mapping=column_mapping)


@router.post("/csv/maintenance-history/commit")
async def commit_maintenance_csv(
    file: UploadFile | None = File(None),
    edited_rows: str | None = Form(None),
    mapping: str | None = Form(None),
    skip_invalid: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    if file is not None:
        await enforce_upload_limit(file)
    column_mapping = json.loads(mapping) if mapping else None
    result = await resolve_commit_validation(service.MAINTENANCE_CSV_SPEC, db, user.tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)
    committed = await service.commit_maintenance_history(db, user.tenant_id, result.valid_rows)
    await touch_freshness(db, user.tenant_id, "predictive_maintenance")
    await recompute_all(db, user.tenant_id)
    await log_audit(
        db, user.tenant_id, user.id, action="commit_maintenance_history", entity_type="maintenance_history",
        details=f"rows_committed={committed} rows_skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )
    return commit_response(result, committed)


# ---------------------------------------------------------------------------
# Asset metric ranges CSV — "what does normal look like for this asset",
# tabular so it can come from a form, a CSV, or continuous DB sync exactly
# like every other operational entity, instead of only the per-asset edit
# form.
# ---------------------------------------------------------------------------

METRIC_RANGE_TEMPLATE_HEADER = "asset_code,metric_name,min,max,unit\n"


@router.get("/csv/metric-ranges/template")
async def metric_ranges_csv_template(_tenant_id: int = Depends(get_tenant_id)):
    return Response(content=METRIC_RANGE_TEMPLATE_HEADER, media_type="text/csv")


@router.post("/csv/metric-ranges/map")
async def map_metric_ranges_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", service.ASSET_METRIC_RANGE_CSV_SPEC)


@router.post("/csv/metric-ranges/validate")
async def validate_metric_ranges_csv(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", service.ASSET_METRIC_RANGE_CSV_SPEC, db, tenant_id, column_mapping=column_mapping)


@router.post("/csv/metric-ranges/commit")
async def commit_metric_ranges_csv(
    file: UploadFile | None = File(None),
    edited_rows: str | None = Form(None),
    mapping: str | None = Form(None),
    skip_invalid: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    if file is not None:
        await enforce_upload_limit(file)
    column_mapping = json.loads(mapping) if mapping else None
    result = await resolve_commit_validation(service.ASSET_METRIC_RANGE_CSV_SPEC, db, user.tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)
    committed = await service.commit_asset_metric_ranges(db, user.tenant_id, result.valid_rows)
    await recompute_all(db, user.tenant_id)
    await log_audit(
        db, user.tenant_id, user.id, action="commit_metric_ranges", entity_type="asset",
        details=f"rows_committed={committed} rows_skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )
    return commit_response(result, committed)


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

@router.get("/recommendations", response_model=list[RecommendationOut])
async def list_recommendations(
    status: str | None = Query(None),
    urgency: str | None = Query(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_recommendations(db, tenant_id, status=status, urgency=urgency)


@router.get("/recommendations/stats")
async def recommendation_stats(
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_recommendation_stats(db, tenant_id)


@router.get("/recommendations/trend")
async def recommendation_trend(
    granularity: str = Query("day", pattern="^(day|week|month|year)$"),
    urgency: str | None = Query(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_recommendation_trend(db, tenant_id, granularity=granularity, urgency=urgency)


@router.post("/recommendations/{rec_id}/acknowledge", response_model=RecommendationOut)
async def acknowledge_recommendation(
    rec_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    try:
        rec = await service.acknowledge_recommendation(db, user.tenant_id, rec_id)
    except service.ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    await log_audit(
        db, user.tenant_id, user.id, action="acknowledge_recommendation", entity_type="recommendation", entity_id=rec.id,
    )
    return rec


@router.post("/recommendations/{rec_id}/action", response_model=RecommendationOut)
async def action_recommendation(
    rec_id: int,
    payload: ActionRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    try:
        rec = await service.action_recommendation(db, user.tenant_id, rec_id, payload.maintenance_history_id)
    except service.ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    await log_audit(
        db, user.tenant_id, user.id, action="action_recommendation", entity_type="recommendation", entity_id=rec.id,
        details=f"maintenance_history_id={payload.maintenance_history_id}",
    )
    return rec


@router.post("/recommendations/{rec_id}/dismiss", response_model=RecommendationOut)
async def dismiss_recommendation(
    rec_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    try:
        rec = await service.dismiss_recommendation(db, user.tenant_id, rec_id)
    except service.ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    await log_audit(
        db, user.tenant_id, user.id, action="dismiss_recommendation", entity_type="recommendation", entity_id=rec.id,
    )
    return rec


# ---------------------------------------------------------------------------
# Manual recompute (demo convenience)
# ---------------------------------------------------------------------------

@router.post("/recompute")
async def manual_recompute(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    await recompute_all(db, user.tenant_id)
    return {"status": "recomputed"}


@router.post("/load-sample-data")
async def load_sample_data(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    result = await service.load_sample_data(db, user.tenant_id, user.id)
    await log_audit(db, user.tenant_id, user.id, action="load_sample_data", entity_type="predictive_maintenance", details=str(result))
    return result


register_module(
    ModuleRegistration(
        key="predictive_maintenance",
        prefix="predictive-maintenance",
        router=router,
        get_summary=service.get_summary,
        get_shift_contribution=service.get_shift_contribution,
    )
)
