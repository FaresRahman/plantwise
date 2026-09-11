"""Every module registers itself here (bottom of its router.py) so main.py can
mount its router, and dashboard/shift-reports can aggregate across modules
generically, without importing each other's internals.

No import-order dependency: registration happens at import time (main.py
imports every module package once), aggregation happens at request time
after every module has already registered.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ModuleSummary, ShiftContribution


@dataclass
class ModuleRegistration:
    key: str
    prefix: str
    router: APIRouter
    get_summary: Callable[[AsyncSession, int], Awaitable[ModuleSummary]] | None = None
    get_shift_contribution: (
        Callable[[AsyncSession, int, datetime, datetime], Awaitable[ShiftContribution]] | None
    ) = None


MODULES: list[ModuleRegistration] = []


def register_module(registration: ModuleRegistration) -> None:
    MODULES.append(registration)
