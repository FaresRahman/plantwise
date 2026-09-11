import { apiRequest } from "./client";

export interface ChatToolCall {
  tool: string;
  args: Record<string, unknown>;
  /** The tool's actual structured return value (e.g. sop_query's
   * {answer, citations, found}) — lets the UI render code-guaranteed data
   * instead of only the LLM's free-text paraphrase of it. Absent on
   * messages sent before this field existed. */
  result?: Record<string, unknown> | null;
}

/** Mirrors sop/schemas.py:SopCitation — shape of one entry in a sop_query
 * tool result's `citations` array. */
export interface SopCitation {
  document_name: string;
  section: string;
  snippet: string;
}

export interface ChatMessageResponse {
  conversation_id: number;
  message: string;
  tool_calls: ChatToolCall[];
}

export interface ChatMessageOut {
  id: number;
  role: "user" | "assistant";
  content: string;
  tool_calls: ChatToolCall[];
  created_at: string;
}

export interface ConversationOut {
  id: number;
  created_at: string;
}

export function sendChatMessage(message: string, conversationId: number | null) {
  return apiRequest<ChatMessageResponse>("/chatbot/message", {
    method: "POST",
    body: { message, conversation_id: conversationId },
  });
}

export function getChatHistory(conversationId: number) {
  return apiRequest<ChatMessageOut[]>(`/chatbot/history?conversation_id=${conversationId}`);
}

export function listConversations() {
  return apiRequest<ConversationOut[]>("/chatbot/conversations");
}
