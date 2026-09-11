"""Line CRUD payload/response shapes and the output-log CSV row shape.
See DEV_BRIEF_SELF.md section 5.2.
"""
from datetime import datetime

from pydantic import BaseModel


class LineBase(BaseModel):
    line_code: str
    name: str
    stations: list[str] = []
    products: list[str] = []
    shift_target_units: int = 0
    ideal_cycle_time_seconds: float = 0.0


class LineCreate(LineBase):
    pass


class LineUpdate(BaseModel):
    line_code: str | None = None
    name: str | None = None
    stations: list[str] | None = None
    products: list[str] | None = None
    shift_target_units: int | None = None
    ideal_cycle_time_seconds: float | None = None


class LineOut(LineBase):
    id: int
    tenant_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DowntimeEventOut(BaseModel):
    """Mirrors engine.get_downtime_events's per-event dict exactly."""

    line_id: str
    station_id: str
    downtime_reason: str | None
    timestamp: datetime
    downtime_minutes: float


class OutputLogQuickIn(BaseModel):
    """Single-row quick-entry alternative to the output-logs CSV — PRD §4.9's
    "quick daily form" for a light daily update (e.g. today's output number)
    without building a CSV for one row.
    """

    station_id: str
    timestamp: datetime | None = None
    units_produced: int = 0
    units_good: int = 0
    units_reject: int = 0
    run_state: str = "run"
    downtime_minutes: float = 0.0
    downtime_reason: str | None = None


class OutputLogOut(BaseModel):
    id: int
    line_id: int
    station_id: str
    timestamp: datetime
    units_produced: int
    units_good: int
    units_reject: int
    run_state: str
    downtime_minutes: float
    downtime_reason: str | None

    model_config = {"from_attributes": True}
