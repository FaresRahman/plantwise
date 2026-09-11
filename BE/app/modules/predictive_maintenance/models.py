from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

CRITICALITY_LEVELS = ("low", "med", "high")
MAINTENANCE_TYPES = ("preventive", "corrective")
URGENCY_LEVELS = ("low", "med", "high")
RECOMMENDATION_STATUSES = ("open", "acknowledged", "actioned", "dismissed")


class Asset(Base):
    __tablename__ = "pm_assets"
    __table_args__ = (UniqueConstraint("tenant_id", "asset_code", name="uq_pm_asset_tenant_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    asset_code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    line_area: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    criticality: Mapped[str] = mapped_column(String(10), nullable=False, default="med")

    # {"vibration": {"min": 0, "max": 3.0, "unit": "mm/s"}, ...}
    monitored_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # {"lubrication": {"interval_hours": 500}, ...}
    service_intervals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    install_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SensorReading(Base):
    __tablename__ = "pm_sensor_readings"
    __table_args__ = (Index("ix_pm_readings_asset_metric_ts", "asset_id", "metric", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("pm_assets.id", ondelete="CASCADE"), nullable=False, index=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    metric: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="")


class MaintenanceHistory(Base):
    __tablename__ = "pm_maintenance_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("pm_assets.id", ondelete="CASCADE"), nullable=False, index=True)

    date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    downtime_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    parts_replaced: Mapped[str | None] = mapped_column(Text, nullable=True)


class FailureCaseSignature(Base):
    """One monitored metric's pre-failure trend, captured automatically the
    moment a corrective MaintenanceHistory row is committed (see
    service.py:_capture_failure_signatures). This is what turns "a past
    failure" from a free-text description match into a structured case the
    engine can actually compare current readings against — see
    engine.py:_check_historical_pattern_match.
    """

    __tablename__ = "pm_failure_case_signatures"
    __table_args__ = (Index("ix_pm_failure_signatures_asset_metric", "asset_id", "metric"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("pm_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    maintenance_history_id: Mapped[int] = mapped_column(
        ForeignKey("pm_maintenance_history.id", ondelete="CASCADE"), nullable=False
    )

    metric: Mapped[str] = mapped_column(String(100), nullable=False)
    # Trend over the days_span preceding the failure — same np.polyfit slope
    # engine.py's _check_trend already computes, just stored rather than
    # thrown away, so a *future* similar trend can be compared against it.
    slope: Mapped[float] = mapped_column(Float, nullable=False)
    start_value: Mapped[float] = mapped_column(Float, nullable=False)
    end_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    days_span: Mapped[float] = mapped_column(Float, nullable=False)

    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Recommendation(Base):
    __tablename__ = "pm_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("pm_assets.id", ondelete="CASCADE"), nullable=False, index=True)

    issue_key: Mapped[str] = mapped_column(String(100), nullable=False)
    issue: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    urgency: Mapped[str] = mapped_column(String(10), nullable=False, default="med")
    estimated_window: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    last_alerted_urgency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    linked_maintenance_id: Mapped[int | None] = mapped_column(
        ForeignKey("pm_maintenance_history.id", ondelete="CASCADE"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
