from pydantic import BaseModel
from typing import Literal


class AlertSettingOut(BaseModel):
    module: str
    urgency_threshold: str
    enabled: bool
    recipients: list[str]


class AlertSettingIn(BaseModel):
    urgency_threshold: Literal["low", "med", "high"] = "high"
    enabled: bool = False
    recipients: list[str] = []
