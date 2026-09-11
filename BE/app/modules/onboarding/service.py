from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import module_registry
from app.modules.onboarding.models import OnboardingProgress
from app.modules.onboarding.schemas import OnboardingStepStatus

SAMPLE_SOP_DIR = Path(__file__).resolve().parents[3] / "sample_data" / "sop"


async def get_status(db: AsyncSession, tenant_id: int) -> list[OnboardingStepStatus]:
    """Completion per registered module — marks complete if the module has
    data (last_updated_at is set). A dedicated /complete endpoint persists
    the final wizard step so the login→onboarding redirect is deterministic."""
    statuses = []
    for registration in module_registry.MODULES:
        if registration.get_summary is None:
            continue
        summary = await registration.get_summary(db, tenant_id)
        statuses.append(
            OnboardingStepStatus(
                module=summary.module,
                title=summary.title,
                complete=summary.last_updated_at is not None,
                headline=summary.headline,
            )
        )
    return statuses


async def is_onboarding_complete(db: AsyncSession, tenant_id: int) -> bool:
    """Returns True once the tenant has explicitly marked onboarding as
    finished (POST /onboarding/complete was called)."""
    result = await db.scalar(
        select(OnboardingProgress).where(
            OnboardingProgress.tenant_id == tenant_id,
            OnboardingProgress.step_key == "onboarding_complete",
        )
    )
    return result is not None


async def mark_onboarding_complete(db: AsyncSession, tenant_id: int) -> None:
    """Idempotently records that onboarding has been completed for this
    tenant. Once set it won't be duplicated — successive calls are a no-op."""
    existing = await db.scalar(
        select(OnboardingProgress).where(
            OnboardingProgress.tenant_id == tenant_id,
            OnboardingProgress.step_key == "onboarding_complete",
        )
    )
    if existing is None:
        db.add(OnboardingProgress(tenant_id=tenant_id, step_key="onboarding_complete"))
        await db.commit()


SAMPLE_DATA_MODULES = ("predictive_maintenance", "production", "inventory", "quality")


async def _load_sop_samples(db: AsyncSession, tenant_id: int, user_id: int) -> list[str]:
    from app.modules.sop import service as sop_service

    seeded = []
    if not SAMPLE_SOP_DIR.exists():
        return seeded

    for path in sorted(SAMPLE_SOP_DIR.glob("*.md")):
        content = path.read_bytes()
        try:
            document = await sop_service.upload_document(db, tenant_id, user_id, path.name, content, None, ["sample"])
            seeded.append(document.name)
        except sop_service.SopError:
            continue
    return seeded


async def load_sample_data(db: AsyncSession, tenant_id: int, user_id: int) -> dict:
    """One-click onboarding "Load sample data" (BRD §5.1/§2.1): seeds Dev B's
    sample SOP documents plus each of Dev A's four modules via their own
    load_sample_data, so the whole demo dataset (including the Quality/
    Production root-cause correlation) is populated in a single call.
    """
    from app.modules.inventory.service import load_sample_data as load_inventory
    from app.modules.predictive_maintenance.service import load_sample_data as load_pm
    from app.modules.production.service import load_sample_data as load_production
    from app.modules.quality.service import load_sample_data as load_quality

    sop_seeded = await _load_sop_samples(db, tenant_id, user_id)

    loaders = {
        "predictive_maintenance": load_pm,
        "production": load_production,
        "inventory": load_inventory,
        "quality": load_quality,
    }
    module_results: dict[str, dict] = {}
    for module_key, loader in loaders.items():
        try:
            module_results[module_key] = await loader(db, tenant_id, user_id)
        except Exception as exc:
            module_results[module_key] = {"error": str(exc)}

    return {"sop_documents_seeded": sop_seeded, "module_results": module_results}
