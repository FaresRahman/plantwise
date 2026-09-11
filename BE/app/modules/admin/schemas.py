from datetime import datetime

from pydantic import BaseModel


class AdminUserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_verified: bool
    is_active: bool

    model_config = {"from_attributes": True}


class RoleUpdateRequest(BaseModel):
    role: str


class ActiveUpdateRequest(BaseModel):
    is_active: bool


class FreshnessRow(BaseModel):
    module: str
    last_updated_at: datetime | None
    expected_cadence_hours: int


class AuditLogEntryOut(BaseModel):
    id: int
    user_email: str | None
    action: str
    entity_type: str
    entity_id: str | None
    details: str | None
    created_at: datetime
