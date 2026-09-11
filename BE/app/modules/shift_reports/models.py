from datetime import date, datetime, time

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ShiftSchedule(Base):
    __tablename__ = "shift_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    areas: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recipients: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Persists the scheduler's auto-generation dedup state (was an in-memory
    # dict, lost on restart and unsafe across multiple app instances) so
    # "already generated today's report for this schedule" survives a
    # restart/redeploy and is shared across instances via the DB row.
    last_generated_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class ShiftReport(Base):
    __tablename__ = "shift_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    shift_schedule_id: Mapped[int | None] = mapped_column(ForeignKey("shift_schedules.id", ondelete="CASCADE"), nullable=True)

    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    compiled_content: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    next_shift_actions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
