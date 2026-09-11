from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.db import get_db
from app.core.deps import get_tenant_id, require_role
from app.core.module_registry import ModuleRegistration, register_module
from app.modules.onboarding import service
from app.modules.onboarding.schemas import LoadSampleDataResponse, OnboardingStepStatus

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "onboarding", "status": "ok"}


@router.get("/status", response_model=list[OnboardingStepStatus])
async def status(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_tenant_id)):
    return await service.get_status(db, tenant_id)


@router.post("/complete")
async def mark_complete(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    await service.mark_onboarding_complete(db, tenant_id)
    await log_audit(
        db, tenant_id, user.id, action="onboarding_complete", entity_type="onboarding",
        details="Onboarding wizard marked complete",
    )
    return {"status": "ok"}


@router.get("/complete", response_model=dict)
async def check_complete(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_tenant_id)):
    complete = await service.is_onboarding_complete(db, tenant_id)
    return {"complete": complete}


@router.post("/load-sample-data", response_model=LoadSampleDataResponse)
async def load_sample_data(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(require_role("admin")),
):
    result = await service.load_sample_data(db, tenant_id, user.id)
    await log_audit(
        db, tenant_id, user.id, action="load_sample_data", entity_type="onboarding",
        details=str(result),
    )
    return LoadSampleDataResponse(**result)


register_module(
    ModuleRegistration(
        key="onboarding",
        prefix="onboarding",
        router=router,
        get_summary=None,
        get_shift_contribution=None,
    )
)
