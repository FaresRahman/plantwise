from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

Criticality = Literal["low", "med", "high"]
Urgency = Literal["low", "med", "high"]
RecommendationStatus = Literal["open", "acknowledged", "actioned", "dismissed"]


class MetricRange(BaseModel):
    min: float
    max: float
    unit: str = ""


class ServiceInterval(BaseModel):
    interval_hours: float


class AssetIn(BaseModel):
    asset_code: str
    name: str
    category: str = ""
    line_area: str = ""
    criticality: Criticality = "med"
    monitored_metrics: dict = {}
    service_intervals: dict = {}
    install_date: date | None = None


class AssetUpdate(BaseModel):
    asset_code: str | None = None
    name: str | None = None
    category: str | None = None
    line_area: str | None = None
    criticality: Criticality | None = None
    monitored_metrics: dict | None = None
    service_intervals: dict | None = None
    install_date: date | None = None


class AssetOut(BaseModel):
    id: int
    tenant_id: int
    asset_code: str
    name: str
    category: str
    line_area: str
    criticality: str
    monitored_metrics: dict
    service_intervals: dict
    install_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReadingOut(BaseModel):
    # Optional (not every ReadingOut list is per-row addressable — the
    # readings-series endpoint used for charting doesn't need it) but always
    # populated for a single reading returned by the quick-log/update endpoints.
    id: int | None = None
    timestamp: datetime
    value: float
    unit: str


class ReadingQuickIn(BaseModel):
    """Single-row quick-entry alternative to the sensor-readings CSV — PRD
    §4.9's "quick daily form" for logging one reading without building a CSV
    for one row.
    """

    metric: str
    value: float
    unit: str = ""
    timestamp: datetime | None = None


class ReadingUpdateIn(BaseModel):
    metric: str | None = None
    value: float | None = None
    unit: str | None = None
    timestamp: datetime | None = None


class MetricRangeQuickIn(BaseModel):
    """Single-row quick-entry alternative to the asset-metric-ranges CSV —
    sets (or replaces) one metric's normal range on this asset, the same
    thing a row in that CSV/DB-sync table does.
    """

    metric_name: str
    min: float
    max: float
    unit: str = ""


class ReadingsSeriesOut(BaseModel):
    asset_id: int
    metric: str
    min: float | None = None
    max: float | None = None
    unit: str | None = None
    readings: list[ReadingOut]


class RecommendationOut(BaseModel):
    id: int
    tenant_id: int
    asset_id: int
    issue_key: str
    issue: str
    evidence: str
    recommended_action: str
    urgency: Urgency
    estimated_window: str
    status: RecommendationStatus
    last_alerted_urgency: Urgency | None
    linked_maintenance_id: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActionRequest(BaseModel):
    maintenance_history_id: int


class MaintenanceHistoryOut(BaseModel):
    id: int
    tenant_id: int
    asset_id: int
    date: date
    type: str
    description: str
    downtime_hours: float
    parts_replaced: str | None

    model_config = {"from_attributes": True}


class MaintenanceHistoryQuickIn(BaseModel):
    """Single-row quick-entry alternative to the maintenance-history CSV —
    same "quick daily form" idea as ReadingQuickIn, for logging one service
    event (e.g. right after fixing something) without building a CSV.

    Field is named event_date, not date — a field named the same as its own
    type (`date: date | None = None`) hits a real Python 3.14 + Pydantic
    incompatibility: the default value binds a class attribute named `date`,
    which then shadows the imported `date` type during lazy annotation
    evaluation, raising "unsupported operand type(s) for |: 'NoneType' and
    'NoneType'". Confirmed by reproducing it in isolation.
    """

    event_date: date | None = None
    type: Literal["preventive", "corrective"]
    description: str = ""
    downtime_hours: float = 0.0
    parts_replaced: str | None = None


class MaintenanceHistoryUpdateIn(BaseModel):
    event_date: date | None = None
    type: Literal["preventive", "corrective"] | None = None
    description: str | None = None
    downtime_hours: float | None = None
    parts_replaced: str | None = None
