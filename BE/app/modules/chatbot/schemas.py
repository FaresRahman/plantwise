from datetime import datetime

from pydantic import BaseModel


class ChatMessageRequest(BaseModel):
    conversation_id: int | None = None
    message: str


class ChatToolCall(BaseModel):
    tool: str
    args: dict = {}
    # The tool's actual structured return value (a ModuleSummary/recommendation/
    # trend/citation object, per core.contracts.ChatToolSpec's dict contract) —
    # PRD §5.3 requires the dashboard and chatbot to "share one representation"
    # rather than the frontend only ever seeing the LLM's free-text answer.
    result: dict | None = None


class ChatMessageResponse(BaseModel):
    conversation_id: int
    message: str
    tool_calls: list[ChatToolCall] = []


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    tool_calls: list[dict]
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}
