from datetime import datetime

from pydantic import BaseModel


class SopDocumentOut(BaseModel):
    id: int
    name: str
    version: int
    source_type: str
    tags: list[str]
    chunk_count: int
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class SopQueryArgs(BaseModel):
    """Chatbot tool args for the sop_query tool the main chatbot calls -
    the only way SOP questions get answered, there is no separate SOP-specific
    endpoint or AI."""

    question: str


class SopCitation(BaseModel):
    document_name: str
    section: str
    snippet: str


class SopQueryResponse(BaseModel):
    answer: str
    citations: list[SopCitation] = []
    found: bool
