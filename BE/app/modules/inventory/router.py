import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
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
from app.modules.inventory import service
from app.modules.inventory.models import Item, StockMovement
from app.modules.inventory.schemas import (
    ItemIn,
    ItemOut,
    ItemUpdate,
    ItemWithProjection,
    StockMovementOut,
    StockMovementQuickIn,
)

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "inventory", "status": "ok"}


# ---------------------------------------------------------------------------
# Item config CRUD
# ---------------------------------------------------------------------------


@router.get("/items", response_model=list[ItemWithProjection])
async def list_items(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_tenant_id)):
    items = await service.list_items(db, tenant_id)
    dependents = await service.get_bom_dependents(db, tenant_id)
    return [await service.item_projection_payload(db, tenant_id, item, dependents=dependents) for item in items]


async def _validate_bom(db: AsyncSession, tenant_id: int, bill_of_materials: dict[str, float] | None) -> None:
    """PRD §4.9 requires unknown SKU/asset/line IDs to be flagged on CSV
    ingestion — the same referential-integrity bar should apply to a BOM
    entered via this form, otherwise it can silently reference a component
    SKU that doesn't (or no longer) exists.
    """
    if not bill_of_materials:
        return
    for component_sku in bill_of_materials:
        if await service.get_item_by_sku(db, tenant_id, component_sku) is None:
            raise HTTPException(status_code=400, detail=f"Bill of materials references unknown SKU '{component_sku}'")


@router.post("/items", response_model=ItemOut, status_code=201)
async def create_item(
    payload: ItemIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    existing = await service.get_item_by_sku(db, user.tenant_id, payload.sku)
    if existing:
        raise HTTPException(status_code=400, detail=f"SKU '{payload.sku}' already exists")
    await _validate_bom(db, user.tenant_id, payload.bill_of_materials)

    item = Item(tenant_id=user.tenant_id, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)

    await log_audit(db, user.tenant_id, user.id, action="create_item", entity_type="item", entity_id=item.id, details=payload.model_dump_json())
    return item


@router.put("/items/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: int,
    payload: ItemUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    item = await service.get_item(db, user.tenant_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    updates = payload.model_dump(exclude_unset=True)
    if "bill_of_materials" in updates:
        await _validate_bom(db, user.tenant_id, updates["bill_of_materials"])
    for field, value in updates.items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)

    await log_audit(db, user.tenant_id, user.id, action="update_item", entity_type="item", entity_id=item.id, details=payload.model_dump_json(exclude_unset=True))
    return item


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    item = await service.get_item(db, user.tenant_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    # Stock movement history FKs into items — clear it first so deleting a
    # configured item doesn't hit a FK-violation on its historical movements.
    await db.execute(delete(StockMovement).where(StockMovement.tenant_id == user.tenant_id, StockMovement.item_id == item_id))
    await db.delete(item)
    await db.commit()

    await log_audit(db, user.tenant_id, user.id, action="delete_item", entity_type="item", entity_id=item_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Item config CSV
# ---------------------------------------------------------------------------

ITEM_TEMPLATE_HEADER = "sku,name,item_type,unit_of_measure,reorder_point,supplier_lead_time_days\n"


@router.get("/csv/items/template")
async def item_csv_template(_tenant_id: int = Depends(get_tenant_id)):
    return Response(content=ITEM_TEMPLATE_HEADER, media_type="text/csv")


@router.post("/csv/items/map")
async def map_item_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", service.ITEM_CSV_SPEC)


@router.post("/csv/items/validate")
async def validate_item_csv(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role("admin")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", service.ITEM_CSV_SPEC, db, tenant_id, column_mapping=column_mapping)


@router.post("/csv/items/commit")
async def commit_item_csv(
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
    result = await resolve_commit_validation(service.ITEM_CSV_SPEC, db, user.tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)
    created, updated = await service.commit_items_config(db, user.tenant_id, result.valid_rows)
    await touch_freshness(db, user.tenant_id, "inventory")
    await log_audit(
        db, user.tenant_id, user.id, action="commit_items_config", entity_type="item",
        details=f"created={created} updated={updated} skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )
    return commit_response(result, created, updated)


@router.post("/load-sample-data")
async def load_sample_data(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin")),
):
    result = await service.load_sample_data(db, user.tenant_id, user.id)
    await log_audit(db, user.tenant_id, user.id, action="load_sample_data", entity_type="inventory", details=str(result))
    return result


@router.post("/items/{item_id}/stock/quick", response_model=StockMovementOut, status_code=201)
async def quick_log_stock(
    item_id: int,
    payload: StockMovementQuickIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    """Single-row alternative to the stock-movements CSV, for logging today's
    current stock level without building a CSV for a single row (PRD §4.9).
    """
    item = await service.get_item(db, user.tenant_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    movement = StockMovement(
        tenant_id=user.tenant_id,
        item_id=item.id,
        timestamp=payload.timestamp or datetime.utcnow(),
        current_qty=payload.current_qty,
        qty_in=payload.qty_in,
        qty_out=payload.qty_out,
        movement_reason=payload.movement_reason,
    )
    db.add(movement)
    await db.commit()
    await db.refresh(movement)
    await touch_freshness(db, user.tenant_id, "inventory")
    await log_audit(
        db, user.tenant_id, user.id, action="quick_log_stock", entity_type="stock_movement", entity_id=movement.id,
        details=f"sku={item.sku}",
    )

    await service.resync_low_stock_alerts(db, user.tenant_id, {item.id})

    return movement


@router.get("/items/{item_id}/history", response_model=list[StockMovementOut])
async def item_history(
    item_id: int,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    item = await service.get_item(db, tenant_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        await db.scalars(
            select(StockMovement)
            .where(
                StockMovement.tenant_id == tenant_id,
                StockMovement.item_id == item_id,
                StockMovement.timestamp >= since,
            )
            .order_by(StockMovement.timestamp.asc())
        )
    ).all()
    return list(rows)


@router.get("/items/{item_id}/consumption-trend")
async def consumption_trend(
    item_id: int,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
):
    item = await service.get_item(db, tenant_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return await service.get_consumption_trend(db, tenant_id, item_id, days)


# ---------------------------------------------------------------------------
# CSV ingestion — stock movements
# ---------------------------------------------------------------------------


@router.get("/csv/stock-movements/template")
async def stock_movements_template(tenant_id: int = Depends(get_tenant_id)):
    return Response(content=service.STOCK_MOVEMENT_CSV_HEADER + "\n", media_type="text/csv")


@router.post("/csv/stock-movements/map")
async def map_stock_movements_csv(
    file: UploadFile = File(...),
    _tenant_id: int = Depends(get_tenant_id),
    _user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    return await map_csv_columns(content, file.filename or "", service.STOCK_MOVEMENT_CSV_SPEC)


@router.post("/csv/stock-movements/validate", response_model=ValidationResult)
async def stock_movements_validate(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    await enforce_upload_limit(file)
    content = await file.read()
    column_mapping = json.loads(mapping) if mapping else None
    return await validate_csv(content, file.filename or "", service.STOCK_MOVEMENT_CSV_SPEC, db, user.tenant_id, column_mapping=column_mapping)


@router.post("/csv/stock-movements/commit")
async def stock_movements_commit(
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
    result = await resolve_commit_validation(service.STOCK_MOVEMENT_CSV_SPEC, db, user.tenant_id, file, edited_rows, column_mapping)
    enforce_commit_gate(result, skip_invalid)
    committed, touched_item_ids = await service.commit_stock_movements(db, user.tenant_id, result.valid_rows)
    await touch_freshness(db, user.tenant_id, "inventory")
    await log_audit(
        db, user.tenant_id, user.id, action="commit_stock_movements", entity_type="stock_movement",
        details=f"rows_committed={committed} rows_skipped={len(result.errors)} filename={file.filename if file else 'edited-preview'}",
    )

    # Only re-alert for items this upload actually touched, matching the
    # quick-log endpoint's scope — previously this re-fired low-stock alerts
    # for every currently-low item tenant-wide on any upload, regardless of
    # whether the upload had anything to do with them.
    await service.resync_low_stock_alerts(db, user.tenant_id, touched_item_ids)

    return commit_response(result, committed)


register_module(
    ModuleRegistration(
        key="inventory",
        prefix="inventory",
        router=router,
        get_summary=service.get_summary,
        get_shift_contribution=service.get_shift_contribution,
    )
)
