"""Line config + OutputLog operational data. See DEV_BRIEF_SELF.md section 5.2
and the more precise spec in the task prompt (supersedes 5.2's algorithm).
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

RUN_STATES = ("run", "idle", "stop")


class Line(Base):
    __tablename__ = "lines"
    __table_args__ = (UniqueConstraint("tenant_id", "line_code", name="uq_lines_tenant_line_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    line_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stations: Mapped[list[str]] = mapped_column(JSONB, default=list)
    products: Mapped[list[str]] = mapped_column(JSONB, default=list)
    shift_target_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ideal_cycle_time_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OutputLog(Base):
    __tablename__ = "output_logs"
    __table_args__ = (Index("ix_output_logs_line_timestamp", "line_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id", ondelete="CASCADE"), nullable=False, index=True)

    station_id: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    units_produced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    units_good: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    units_reject: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_state: Mapped[str] = mapped_column(String(10), nullable=False, default="run")
    downtime_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    downtime_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
