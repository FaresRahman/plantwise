"""Agentic chatbot: discovers tools generically from core.contracts.TOOL_REGISTRY
(never hardcodes Dev A's function names), lets the LLM decide whether a
question needs RAG (SOP tool), structured data analysis (any other
registered tool), both, or neither. See DEV_BRIEF_TEAMMATE.md section 5.3.

Cross-module questions (PRD flow #4, e.g. "is Line 2 going to hit target,
and do we have material for tomorrow?") are handled by construction, not by
any special-cased logic here: create_react_agent's loop calls as many
registered tools as the model decides it needs in one turn (production_gap
+ inventory_runout, say), bounded by MAX_TURNS. Do NOT build a monolithic
"cross_module_query" tool that reaches into multiple modules' data itself —
that would duplicate what this loop already does and break the
one-tool-per-module ownership convention every other module follows.
"""
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import TOOL_REGISTRY
from app.core.llm import get_chat_llm
from app.modules.chatbot.models import Conversation, Message

SYSTEM_PROMPT = (
    "You are Plantwise's operations assistant for a manufacturing plant. You have tools for two kinds "
    "of questions: (1) SOP/procedure 'how/what' questions - use the sop_query tool and always cite the "
    "document and section it returns; (2) data questions about maintenance, production, inventory, or "
    "quality ('why/how much/is X okay') - use the relevant registered data tool and answer with the "
    "actual figures it returns. For 'why is line X behind/down' questions specifically, prefer "
    "production_downtime_detail (station-level stop counts, durations, time windows, and which OEE factor "
    "is the actual drag) over production_gap_to_target, which only gives aggregate numbers.\n\n"
    "Several modules also register a '..._list_...' tool (e.g. predictive_maintenance_list_assets, "
    "production_list_lines, inventory_list_items, quality_list_characteristics). Call the relevant one "
    "whenever the user asks for a list/registry of something, or when a lookup tool returns a "
    "'not found' error - use the list tool to find the right identifier and retry, rather than giving up "
    "immediately.\n\n"
    "Hard rule: never invent a figure, citation, or fact. If no tool returns relevant data, or a tool "
    "isn't registered yet for what's being asked, say so explicitly and name what's missing - do not "
    "fill the gap from general knowledge.\n\n"
    "Scope rule: You only answer questions about this manufacturing plant's operations - predictive "
    "maintenance, production, inventory, quality, SOPs, shift reports, and plant floor topics. If a user "
    "asks about something completely unrelated to plant operations (e.g., general knowledge, entertainment, "
    "coding, politics), decline politely and professionally. Say, in your own words but keeping this meaning: "
    "'I'm an AI assistant built to answer questions about your plant's data only. Could you please ask "
    "something related to your plant, such as equipment, production, inventory, quality, SOPs, or shift "
    "reports?' Keep the tone warm and courteous, never curt. Do not answer off-topic questions.\n\n"
    "Most data tools also return a 'freshness' field ({'last_updated_at', 'is_stale'}). If 'is_stale' is "
    "true, you must say so explicitly in your answer (e.g. 'this data hasn't been updated since <date> and "
    "may be out of date') before giving the figures - never present stale numbers as if they were current."
)

MAX_TURNS = 8


def _wrap_tool(spec, db: AsyncSession, tenant_id: int) -> StructuredTool:
    async def _call(**kwargs):
        result = await spec.fn(db, tenant_id, **kwargs)
        return json.dumps(result, default=str)

    return StructuredTool.from_function(
        coroutine=_call,
        name=spec.name,
        description=spec.description,
        args_schema=spec.args_schema,
    )


def _history_to_messages(rows: list[Message]) -> list:
    messages = []
    for row in rows:
        if row.role == "user":
            messages.append(HumanMessage(content=row.content))
        else:
            messages.append(AIMessage(content=row.content))
    return messages


def _extract_tool_calls(messages: list) -> list[dict]:
    """Pairs each tool invocation with the actual structured result the tool
    returned (from the matching ToolMessage), not just the call's name/args —
    PRD §5.3's "dashboard and chatbot share one representation" requirement
    means the frontend needs the real object (recommendation, trend, SOP
    citations, ...), not only the LLM's paraphrase of it.
    """
    results_by_call_id: dict[str, object] = {}
    for m in messages:
        if isinstance(m, ToolMessage):
            try:
                results_by_call_id[m.tool_call_id] = json.loads(m.content)
            except (TypeError, ValueError):
                results_by_call_id[m.tool_call_id] = m.content

    calls = []
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                result = results_by_call_id.get(tc.get("id"))
                calls.append({
                    "tool": tc["name"],
                    "args": tc.get("args", {}),
                    "result": result if isinstance(result, dict) else None,
                })
    return calls


async def send_message(
    db: AsyncSession, tenant_id: int, user_id: int, conversation_id: int | None, user_text: str
) -> tuple[int, str, list[dict]]:
    if conversation_id is not None:
        conversation = await db.scalar(
            select(Conversation).where(Conversation.tenant_id == tenant_id, Conversation.id == conversation_id)
        )
        if conversation is None:
            raise ValueError("Conversation not found")
    else:
        conversation = Conversation(tenant_id=tenant_id, user_id=user_id)
        db.add(conversation)
        await db.flush()

    prior_rows = list(
        await db.scalars(
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
        )
    )
    db.add(Message(tenant_id=tenant_id, conversation_id=conversation.id, role="user", content=user_text))
    await db.commit()

    tools = [_wrap_tool(spec, db, tenant_id) for spec in TOOL_REGISTRY]
    agent = create_react_agent(get_chat_llm(), tools, prompt=SYSTEM_PROMPT)

    history = _history_to_messages(prior_rows) + [HumanMessage(content=user_text)]
    result = await agent.ainvoke({"messages": history}, config={"recursion_limit": MAX_TURNS * 2 + 1})

    result_messages = result["messages"]
    final_message = result_messages[-1]
    answer = final_message.content if isinstance(final_message.content, str) else str(final_message.content)
    tool_calls = _extract_tool_calls(result_messages)

    db.add(
        Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            tool_calls=tool_calls,
        )
    )
    await db.commit()

    return conversation.id, answer, tool_calls


async def get_history(db: AsyncSession, tenant_id: int, conversation_id: int) -> list[Message]:
    return list(
        await db.scalars(
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
    )


async def list_conversations(db: AsyncSession, tenant_id: int, user_id: int) -> list[Conversation]:
    return list(
        await db.scalars(
            select(Conversation)
            .where(Conversation.tenant_id == tenant_id, Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
        )
    )
