from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

URGENCY_LEVELS = ("low", "med", "high")


class AlertSetting(Base):
    """Per-tenant, per-module alert configuration. Admin-configurable; a
    missing row means "use the module's hard-coded default" (see
    service.DEFAULT_SETTINGS) rather than every tenant needing a seeded row.
    """

    __tablename__ = "alert_settings"
    __table_args__ = (UniqueConstraint("tenant_id", "module", name="uq_alert_settings_tenant_module"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    module: Mapped[str] = mapped_column(String(100), nullable=False)
    urgency_threshold: Mapped[str] = mapped_column(String(10), nullable=False, default="high")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recipients: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class SentAlert(Base):
    """De-dup ledger: one row per (tenant, asset, issue). A recommendation
    alert only re-sends when the new urgency outranks last_urgency — a
    still-open recommendation at the same urgency doesn't re-fire on every
    refresh, per the PRD.
    """

    __tablename__ = "sent_alerts"
    __table_args__ = (UniqueConstraint("tenant_id", "asset_name", "issue", name="uq_sent_alerts_tenant_asset_issue"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    asset_name: Mapped[str] = mapped_column(String(255), nullable=False)
    issue: Mapped[str] = mapped_column(String(255), nullable=False)
    last_urgency: Mapped[str] = mapped_column(String(10), nullable=False)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
