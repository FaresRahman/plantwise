from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CharacteristicIn(BaseModel):
    part_id: str
    characteristic_name: str
    nominal_value: float
    tolerance: float
    inspection_type: str = ""
    line_id: str = ""
    station_id: str = ""
    defect_categories: list[str] = []


class CharacteristicOut(BaseModel):
    id: int
    tenant_id: int
    part_id: str
    characteristic_name: str
    nominal_value: float
    tolerance: float
    inspection_type: str
    line_id: str
    station_id: str
    defect_categories: list[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DefectBreakdownItem(BaseModel):
    defect_type: str | None
    count: int
    pct_of_failures: float


class DefectTrend(BaseModel):
    recent_total: int
    recent_fail: int
    recent_rate: float
    baseline_total: int
    baseline_fail: int
    baseline_rate: float
    is_spike: bool
    defect_breakdown: list[DefectBreakdownItem]


class ToleranceDrift(BaseModel):
    recent_avg_measured: float | None
    baseline_avg_measured: float | None
    recent_limit_fraction: float | None
    baseline_limit_fraction: float | None
    is_drifting_toward_limit: bool
    is_approaching_limit: bool


class CharacteristicTrendOut(DefectTrend):
    characteristic_id: int
    part_id: str
    characteristic_name: str
    root_cause: str | None = None
    tolerance_drift: ToleranceDrift | None = None


class InspectionQuickIn(BaseModel):
    """Single-row quick-entry alternative to the inspection-records CSV — PRD
    §4.9's "quick daily form" for logging one inspection result without
    building a CSV for one row.
    """

    measured_value: float
    pass_fail: bool
    defect_type: str | None = None
    station_id: str | None = None
    inspector: str = ""
    timestamp: datetime | None = None


class InspectionRecordOut(BaseModel):
    id: int
    part_id: str
    timestamp: datetime
    characteristic_name: str
    measured_value: float
    pass_fail: bool
    defect_type: str | None
    line_id: str
    station_id: str
    inspector: str

    model_config = ConfigDict(from_attributes=True)


class QualityHoldIn(BaseModel):
    part_id: str
    lot_number: str
    reason: str


class QualityHoldRelease(BaseModel):
    """Required at release time — mirrors QualityHoldIn.reason: a hold needs
    a reason to open, so it needs one to close, so there's always a record
    of why a held lot was safe to ship.
    """

    release_note: str


class QualityHoldOut(BaseModel):
    id: int
    tenant_id: int
    part_id: str
    lot_number: str
    reason: str
    status: str
    created_by: int
    created_at: datetime
    released_at: datetime | None
    released_by: int | None
    release_note: str | None

    model_config = ConfigDict(from_attributes=True)
