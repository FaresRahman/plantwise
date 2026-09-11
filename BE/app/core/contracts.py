"""Shared shapes every module speaks so the integrative features (dashboard,
chatbot, shift reports) never need to reach into another module's internals.
See DEV_BRIEF_SELF.md / DEV_BRIEF_TEAMMATE.md section 4 for how these are used.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class ModuleSummary(BaseModel):
    """What a module reports for its dashboard card."""

    module: str
    title: str
    status: Literal["ok", "warning", "critical"] = "ok"
    headline: str = ""
    metrics: list[dict] = []
    last_updated_at: datetime | None = None
    is_stale: bool = False
    # None when the module has no per-tenant cadence configured yet (e.g. SOP,
    # Shift Reports, which don't use daily-batch freshness). Lets the FE
    # distinguish "amber: a bit stale" from "red: badly overdue" (BRD §4.7)
    # instead of a single stale/fresh boolean.
    expected_cadence_hours: int | None = None
    alerts_count: int | None = None  # None = no data to evaluate; 0 = confirmed zero alerts
    drilldown_path: str = ""


class ShiftContribution(BaseModel):
    """What a module contributes to a shift-report handover for a given
    (tenant, time window). Modules with nothing to say (SOP, chatbot,
    notifications) simply don't implement get_shift_contribution.
    """

    module: str
    summary_text: str = ""
    data: dict = {}
    open_items: list[str] = []


@dataclass
class ChatToolSpec:
    """A callable the chatbot agent may invoke. `fn` signature must be
    `async def fn(db, tenant_id, **args) -> dict` where **args matches
    `args_schema`'s fields. Never invents figures — return only what the
    query actually found, including "no data" states.
    """

    name: str
    description: str
    args_schema: type[BaseModel]
    fn: Callable[..., Awaitable[dict[str, Any]]]


TOOL_REGISTRY: list[ChatToolSpec] = []


def register_tool(spec: ChatToolSpec) -> None:
    TOOL_REGISTRY.append(spec)
