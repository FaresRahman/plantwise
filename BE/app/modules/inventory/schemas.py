from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ItemType = Literal["raw", "wip", "finished"]


class ItemIn(BaseModel):
    sku: str
    name: str
    item_type: ItemType = "raw"
    unit_of_measure: str = "unit"
    reorder_point: float = 0
    supplier_lead_time_days: int = 0
    bill_of_materials: dict[str, float] | None = None


class ItemUpdate(BaseModel):
    sku: str | None = None
    name: str | None = None
    item_type: ItemType | None = None
    unit_of_measure: str | None = None
    reorder_point: float | None = None
    supplier_lead_time_days: int | None = None
    bill_of_materials: dict[str, float] | None = None


class ItemOut(BaseModel):
    id: int
    tenant_id: int
    sku: str
    name: str
    item_type: str
    unit_of_measure: str
    reorder_point: float
    supplier_lead_time_days: int
    bill_of_materials: dict[str, float] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ItemProjection(BaseModel):
    # None means no stock-movement rows exist yet — level is unknown, not 0.
    current_qty: float | None
    daily_consumption: float
    days_to_runout: float | None = None
    runout_date: str | None = None
    is_low: bool
    has_data: bool


class ItemWithProjection(ItemOut):
    projection: ItemProjection


class StockMovementOut(BaseModel):
    id: int
    item_id: int
    timestamp: datetime
    current_qty: float
    qty_in: float
    qty_out: float
    movement_reason: str | None = None

    model_config = {"from_attributes": True}


class StockMovementQuickIn(BaseModel):
    """Single-row quick-entry alternative to the stock-movements CSV — PRD
    §4.9's "quick daily form" for a light daily update (e.g. current stock)
    without building a CSV for one row.
    """

    timestamp: datetime | None = None
    current_qty: float
    qty_in: float = 0
    qty_out: float = 0
    movement_reason: str | None = None
