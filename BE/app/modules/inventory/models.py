from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

ITEM_TYPES = ("raw", "wip", "finished")


class Item(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (UniqueConstraint("tenant_id", "sku", name="uq_inventory_items_tenant_sku"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False, default="raw")
    unit_of_measure: Mapped[str] = mapped_column(String(50), nullable=False, default="unit")
    reorder_point: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    supplier_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # {"RM-STEEL-1": 2, "RM-BOLT-8": 4} — component sku -> qty; only meaningful for finished goods
    bill_of_materials: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StockMovement(Base):
    __tablename__ = "inventory_stock_movements"
    __table_args__ = (Index("ix_inventory_stock_movements_item_ts", "item_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    current_qty: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    qty_in: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    qty_out: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    movement_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
