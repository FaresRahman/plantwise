import React from "react";

/** Shared "nothing here yet" panel used across every module. A dashed border
 * and muted icon read clearly as "empty" (vs. a plain white surface card,
 * which can look like a broken/loading state instead of an intentional one). */
export function EmptyState({ title, message }: { title: string; message?: string }) {
  return (
    <div
      style={{
        padding: "40px 24px",
        textAlign: "center",
        border: "1px dashed var(--color-border-strong)",
        borderRadius: "var(--radius-xl)",
        background: "var(--color-neutral-50)",
      }}
    >
      <div
        style={{
          width: 40,
          height: 40,
          margin: "0 auto 14px",
          borderRadius: "50%",
          background: "var(--color-neutral-100)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-neutral-400)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="3" />
          <path d="M9 9h6v6H9z" />
        </svg>
      </div>
      <h3 style={{ margin: "0 0 6px", fontSize: 15, color: "var(--color-text-primary)" }}>{title}</h3>
      {message && <p style={{ margin: "0 auto", maxWidth: 360, fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{message}</p>}
    </div>
  );
}
