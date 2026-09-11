from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Characteristic(Base):
    """A quality characteristic tracked for a part at a given line/station,
    e.g. "bore diameter" on part P-100 at Line 3 / Station 2.
    """

    __tablename__ = "quality_characteristics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    part_id: Mapped[str] = mapped_column(String(100), nullable=False)
    characteristic_name: Mapped[str] = mapped_column(String(255), nullable=False)
    nominal_value: Mapped[float] = mapped_column(Float, nullable=False)
    tolerance: Mapped[float] = mapped_column(Float, nullable=False)
    inspection_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    line_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    station_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # e.g. ["surface scratch", "burr", "dimension out-of-spec"]
    defect_categories: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_quality_char_tenant_part_name", "tenant_id", "part_id", "characteristic_name"),
    )


class InspectionRecord(Base):
    """One inspection reading/result for a part's characteristic, ingested via
    the CSV pipeline.
    """

    __tablename__ = "quality_inspection_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    part_id: Mapped[str] = mapped_column(String(100), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    characteristic_name: Mapped[str] = mapped_column(String(255), nullable=False)
    measured_value: Mapped[float] = mapped_column(Float, nullable=False)
    pass_fail: Mapped[bool] = mapped_column(Boolean, nullable=False)
    defect_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    station_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    inspector: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    __table_args__ = (
        Index("ix_quality_insp_tenant_line_ts", "tenant_id", "line_id", "timestamp"),
        Index("ix_quality_insp_tenant_part_char_ts", "tenant_id", "part_id", "characteristic_name", "timestamp"),
    )


class QualityHold(Base):
    """A lot/batch placed on hold pending QC disposition — this is what the
    PRD's shift-report example means by "quality (incl. holds)" ("Lot #4471
    held for QC — do not release."). It's a disposition decision an
    Admin/Operator makes, not a measurement, so it's independent of
    InspectionRecord.
    """

    __tablename__ = "quality_holds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    part_id: Mapped[str] = mapped_column(String(100), nullable=False)
    lot_number: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")  # open | released
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    # Required at release time (enforced in service.release_hold) — a hold
    # needs a reason to open, so it needs one to close too; without this a
    # lot could be cleared with no record of why it was safe to ship.
    release_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (Index("ix_quality_holds_tenant_status", "tenant_id", "status"),)
