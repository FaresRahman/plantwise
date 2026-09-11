from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user, get_tenant_id
from app.core.module_registry import ModuleRegistration, register_module
from app.modules.chatbot import service
from app.modules.chatbot.schemas import (
    ChatMessageOut,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatToolCall,
    ConversationOut,
)

router = APIRouter()


@router.get("/health")
async def health():
    return {"module": "chatbot", "status": "ok"}


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    payload: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(get_current_user),
):
    try:
        conversation_id, answer, tool_calls = await service.send_message(
            db, tenant_id, user.id, payload.conversation_id, payload.message
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ChatMessageResponse(
        conversation_id=conversation_id,
        message=answer,
        tool_calls=[ChatToolCall(**tc) for tc in tool_calls],
    )


@router.get("/history", response_model=list[ChatMessageOut])
async def history(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    _user=Depends(get_current_user),
):
    return await service.get_history(db, tenant_id, conversation_id)


@router.get("/conversations", response_model=list[ConversationOut])
async def conversations(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_tenant_id),
    user=Depends(get_current_user),
):
    return await service.list_conversations(db, tenant_id, user.id)


# No get_summary/get_shift_contribution — chatbot has no dashboard card or
# shift-report section of its own.
register_module(
    ModuleRegistration(
        key="chatbot",
        prefix="chatbot",
        router=router,
        get_summary=None,
        get_shift_contribution=None,
    )
)
