import React from "react";

/** Shimmering placeholder rows, used instead of a plain "Loading..." string
 * so a page's first paint already suggests its final layout (rows/cards)
 * rather than a flash of bare text. */
export function Skeleton({ rows = 3, height = 44 }: { rows?: number; height?: number }) {
  return (
    <div className="table-card">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ padding: "0 16px", borderBottom: i < rows - 1 ? "1px solid var(--color-border-subtle)" : "none" }}>
          <div
            style={{
              height,
              borderRadius: "var(--radius-md)",
              margin: "10px 0",
              background: "linear-gradient(90deg, var(--color-neutral-100) 25%, var(--color-neutral-50) 37%, var(--color-neutral-100) 63%)",
              backgroundSize: "400% 100%",
              animation: "pw-shimmer 1.4s ease infinite",
            }}
          />
        </div>
      ))}
      <style>{`
        @keyframes pw-shimmer {
          0% { background-position: 100% 50%; }
          100% { background-position: 0 50%; }
        }
      `}</style>
    </div>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: size,
        height: size,
        border: "2px solid var(--color-neutral-200)",
        borderTopColor: "var(--color-primary-600)",
        borderRadius: "50%",
        animation: "pw-spin 0.7s linear infinite",
      }}
    >
      <style>{`
        @keyframes pw-spin { to { transform: rotate(360deg); } }
      `}</style>
    </span>
  );
}
