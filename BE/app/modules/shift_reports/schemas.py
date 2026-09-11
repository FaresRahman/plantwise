from datetime import datetime, time

from pydantic import BaseModel


class ShiftScheduleIn(BaseModel):
    name: str
    start_time: time
    end_time: time
    areas: list[str] = []
    recipients: list[str] = []


class ShiftScheduleOut(ShiftScheduleIn):
    id: int

    model_config = {"from_attributes": True}


class GenerateReportRequest(BaseModel):
    shift_schedule_id: int | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None


class ShiftReportQueryArgs(BaseModel):
    """Structured-query DSL for the shift_reports_query chat tool — the model
    fills in these typed fields, never SQL. schedule_name is resolved via
    core.dimension_resolver against this tenant's actual schedule names
    (fuzzy match + deterministic clarification), not trusted verbatim.
    """

    schedule_name: str | None = None
    limit: int = 5


class ShiftReportOut(BaseModel):
    id: int
    shift_schedule_id: int | None
    window_start: datetime
    window_end: datetime
    compiled_content: list[dict]
    next_shift_actions: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}
