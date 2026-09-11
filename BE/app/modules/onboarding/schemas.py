from pydantic import BaseModel


class OnboardingStepStatus(BaseModel):
    module: str
    title: str
    complete: bool
    headline: str


class LoadSampleDataResponse(BaseModel):
    sop_documents_seeded: list[str]
    module_results: dict[str, dict]
