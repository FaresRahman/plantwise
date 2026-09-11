"""Cross-cutting tables that every module either FKs into or writes to.

These live in core (not in any one module) specifically to avoid circular
imports between modules and to keep tenant isolation / audit / freshness
consistent no matter who writes the code that touches them.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ModuleFreshness(Base):
    """One row per (tenant, module). Updated whenever operational data is
    committed for that module. Drives the dashboard's freshness badge.
    """

    __tablename__ = "module_freshness"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(100), nullable=False)
    # No column-level onupdate: core.ingestion.touch_freshness already sets
    # this explicitly on every commit. A column-level onupdate would fire on
    # *any* UPDATE to this row — including just setting last_nudged_at below —
    # silently resetting staleness the moment a nudge is recorded.
    last_updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expected_cadence_hours: Mapped[int] = mapped_column(Integer, default=24)
    # Dedup for missing-data nudges (BRD §5.4/§6.2) — only nudge again after
    # a full cadence period has passed since the last nudge, not on every
    # dashboard load.
    last_nudged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
