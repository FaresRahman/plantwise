from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ModuleSummary
from app.core.db import get_db
from app.core.deps import get_tenant_id
from app.core.module_registry import ModuleRegistration, register_module
from app.modules.dashboard import service

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "dashboard", "status": "ok"}


@router.get("/summary", response_model=list[ModuleSummary])
async def dashboard_summary(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_tenant_id)):
    return await service.get_all_summaries(db, tenant_id)


register_module(
    ModuleRegistration(
        key="dashboard",
        prefix="dashboard",
        router=router,
        get_summary=None,
        get_shift_contribution=None,
    )
)
