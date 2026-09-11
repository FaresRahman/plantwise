import React, { useEffect, useRef, useState } from "react";

import { ChatToolCall, SopCitation, getChatHistory, listConversations, sendChatMessage } from "../../api/chatbot";
import { MarkdownLite } from "../../components/MarkdownLite";

interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
  tool_calls: ChatToolCall[];
}

const SUGGESTIONS = [
  "Give me the asset list",
  "Is Line 2 going to hit target today?",
  "What's the lockout/tagout procedure for the press?",
  "Any quality issues today?",
];

function ToolChip({ tool }: { tool: string }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        fontSize: 10.5,
        fontWeight: 700,
        letterSpacing: ".02em",
        textTransform: "uppercase",
        background: "var(--color-primary-50)",
        color: "var(--color-primary-700)",
        border: "1px solid var(--color-primary-100)",
        borderRadius: "var(--radius-full)",
        padding: "3px 10px",
      }}
    >
      {tool.replace(/_/g, " ")}
    </span>
  );
}

/**
 * Assistant answers that cite a source document put it on its own trailing
 * "Source: ..." line(s) (per the backend system prompt: "always cite the
 * document and section"). Split those off so they can render as a distinct,
 * quotable citation footer instead of blending into the prose — citations
 * are the core trust mechanism for document-grounded answers. Pure string
 * splitting, no change to what content is fetched/stored.
 */
const CITATION_LINE_RE = /^\s*\[?\s*source\s*:\s*(.+?)\s*\]?\s*$/i;

function splitCitations(content: string): { body: string; citations: string[] } {
  const trimmed = content.replace(/\r\n/g, "\n").replace(/\s+$/, "");
  const lines = trimmed.split("\n");
  const citations: string[] = [];
  let end = lines.length;
  while (end > 0 && CITATION_LINE_RE.test(lines[end - 1])) {
    citations.unshift(CITATION_LINE_RE.exec(lines[end - 1])![1].trim());
    end--;
  }
  if (citations.length === 0) return { body: content, citations: [] };
  return { body: lines.slice(0, end).join("\n").trim(), citations };
}

/**
 * Prefers the sop_query tool's actual structured `citations` result over the
 * regex-parsed "Source: ..." line — the trailing-line convention only works
 * if the model reliably reproduces that exact format, while the tool's
 * result is code-guaranteed. Falls back to the regex parse (still done in
 * splitCitations, called separately) for older stored messages sent before
 * tool results were captured, or if a tool ever omits `result`.
 */
function structuredCitationsFrom(toolCalls: ChatToolCall[]): string[] {
  const citations: string[] = [];
  for (const tc of toolCalls) {
    if (tc.tool !== "sop_query" || !tc.result) continue;
    const rows = (tc.result.citations as SopCitation[] | undefined) ?? [];
    for (const c of rows) {
      citations.push(c.section ? `${c.document_name} §${c.section}` : c.document_name);
    }
  }
  return citations;
}

function CitationFooter({ citations }: { citations: string[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--color-border-subtle)" }}>
      {citations.map((c, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 8,
            fontFamily: "var(--font-family-mono)",
            fontSize: 11.5,
            lineHeight: 1.4,
            color: "var(--color-info-800)",
            background: "var(--color-info-50)",
            borderLeft: "3px solid var(--color-info-600)",
            borderRadius: "0 var(--radius-md) var(--radius-md) 0",
            padding: "6px 10px",
          }}
        >
          <span style={{ textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 700, flex: "none" }}>Source</span>
          <span>{c}</span>
        </div>
      ))}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div style={{ display: "flex", gap: 4, padding: "10px 0" }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "var(--color-neutral-400)",
            animation: "pw-bounce 1.2s infinite ease-in-out",
            animationDelay: `${i * 0.15}s`,
          }}
        />
      ))}
      <style>{`
        @keyframes pw-bounce {
          0%, 80%, 100% { transform: translateY(0); opacity: .5; }
          40% { transform: translateY(-4px); opacity: 1; }
        }
      `}</style>
    </div>
  );
}

export default function ChatbotPage() {
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Set the instant the user sends anything — guards the history-restore
  // effect below from clobbering a message sent while that fetch was still
  // in flight (it would otherwise overwrite `messages`/`conversationId` with
  // stale fetched data once it resolves).
  const interactedRef = useRef(false);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  // Restore the most recent conversation on load — otherwise a refresh loses
  // a chat that's already persisted server-side (Conversation/Message tables).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const conversations = await listConversations();
        const latest = conversations[0];
        if (!latest || cancelled) return;
        const history = await getChatHistory(latest.id);
        if (cancelled || interactedRef.current) return;
        setConversationId(latest.id);
        setMessages(history.map((m) => ({ role: m.role, content: m.content, tool_calls: m.tool_calls })));
      } catch {
        // No prior conversation, or history fetch failed — start fresh, same
        // as today's behavior; not a user-facing error.
      } finally {
        if (!cancelled) setLoadingHistory(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function send(text: string) {
    if (!text.trim()) return;
    interactedRef.current = true;
    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: text, tool_calls: [] }]);
    setSending(true);
    try {
      const res = await sendChatMessage(text, conversationId);
      setConversationId(res.conversation_id);
      setMessages((prev) => [...prev, { role: "assistant", content: res.message, tool_calls: res.tool_calls }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
    } finally {
      setSending(false);
    }
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    await send(input);
  }

  function handleNewConversation() {
    setConversationId(null);
    setMessages([]);
    setError(null);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 120px)", maxWidth: 860, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 36,
              height: 36,
              flex: "none",
              background: "var(--color-accent-600)",
              color: "var(--color-accent-ink)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--font-family-display)",
              fontWeight: 800,
              fontSize: 16,
              clipPath: "polygon(18% 0, 100% 0, 100% 82%, 82% 100%, 0 100%, 0 18%)",
              boxShadow: "inset 0 0 0 1px rgba(255,255,255,.18)",
            }}
          >
            P
          </div>
          <div>
            <div style={{ fontFamily: "var(--font-family-display)", fontSize: 18, fontWeight: 700, lineHeight: 1.1 }}>Plantwise AI</div>
            <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>Grounded in your data and documents</div>
          </div>
        </div>
        {messages.length > 0 && (
          <button className="btn-ghost" onClick={handleNewConversation}>
            New conversation
          </button>
        )}
      </div>

      <div
        ref={scrollRef}
        className="surface pw-scroll"
        style={{
          flex: 1,
          padding: 20,
          overflowY: "auto",
          marginBottom: 12,
          display: "flex",
          flexDirection: "column",
          gap: 14,
          // Soft two-tone glow wash instead of a flat fill or a dot grid —
          // reads as a polished AI-chat surface rather than engineering
          // graph paper. Built entirely from existing theme tokens (a cool
          // info tint from the top-left, a warm primary tint from the
          // bottom-right) so it stays correctly subtle — and correctly
          // inverted — in both light and dark themes.
          backgroundColor: "var(--color-surface-default)",
          backgroundImage:
            "radial-gradient(900px 520px at 6% -10%, var(--color-info-50), transparent 60%), " +
            "radial-gradient(700px 520px at 104% 110%, var(--color-primary-50), transparent 55%)",
        }}
      >
        {messages.length === 0 && loadingHistory && (
          <div style={{ margin: "auto", color: "var(--color-text-tertiary)", fontSize: 13 }}>Loading conversation…</div>
        )}

        {messages.length === 0 && !loadingHistory && (
          <div style={{ margin: "auto", maxWidth: 480, textAlign: "center" }}>
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: "var(--radius-xl)",
                background: "var(--color-primary-50)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 14px",
              }}
            >
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--color-primary-600)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <p style={{ color: "var(--color-text-secondary)", fontSize: 14, marginBottom: 14 }}>
              One assistant for the whole plant: ask about SOPs, maintenance, production, inventory, or quality,
              all grounded in your uploaded data.
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="btn-secondary"
                  style={{ fontSize: 12, padding: "7px 12px" }}
                  onClick={() => send(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => {
          const isUser = m.role === "user";
          const { body, citations: regexCitations } = isUser ? { body: m.content, citations: [] as string[] } : splitCitations(m.content);
          const structuredCitations = isUser ? [] : structuredCitationsFrom(m.tool_calls);
          const citations = structuredCitations.length > 0 ? structuredCitations : regexCitations;
          return (
            <div key={i} style={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start" }}>
              <div style={{ maxWidth: "78%", display: "flex", flexDirection: "column", alignItems: isUser ? "flex-end" : "flex-start" }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-tertiary)", marginBottom: 4, textTransform: "uppercase", letterSpacing: ".04em" }}>
                  {isUser ? "You" : "AI"}
                </div>
                <div
                  style={{
                    fontFamily: "var(--font-family-sans)",
                    fontSize: 14,
                    lineHeight: 1.55,
                    whiteSpace: isUser ? "pre-wrap" : "normal",
                    padding: "12px 16px",
                    borderRadius: isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                    background: isUser ? "var(--color-fill-solid)" : "var(--color-neutral-50)",
                    color: isUser ? "var(--color-fill-solid-fg)" : "var(--color-text-primary)",
                    border: isUser ? "none" : "1px solid var(--color-border-default)",
                  }}
                >
                  {isUser ? body : <MarkdownLite content={body} />}
                  {!isUser && citations.length > 0 && <CitationFooter citations={citations} />}
                </div>
                {m.tool_calls.length > 0 && (
                  <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                    {m.tool_calls.map((tc, j) => (
                      <ToolChip key={j} tool={tc.tool} />
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {sending && (
          <div style={{ display: "flex", justifyContent: "flex-start" }}>
            <div style={{ padding: "4px 16px", borderRadius: "16px 16px 16px 4px", background: "var(--color-neutral-50)", border: "1px solid var(--color-border-default)" }}>
              <TypingIndicator />
            </div>
          </div>
        )}
      </div>

      {error && <div style={{ color: "var(--color-error-600)", fontSize: 13, marginBottom: 8 }}>{error}</div>}

      <form onSubmit={handleSend} style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          className="input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question..."
          style={{ flex: 1, borderRadius: 9999 }}
        />
        <button
          type="submit"
          className="btn-primary"
          disabled={sending || !input.trim()}
          style={{ borderRadius: "50%", width: 42, height: 42, minWidth: 42, padding: 0, display: "flex", alignItems: "center", justifyContent: "center", flex: "none" }}
          aria-label="Send"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </form>
    </div>
  );
}
