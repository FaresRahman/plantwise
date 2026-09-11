import React from "react";

export interface TabItem {
  key: string;
  label: string;
}

/** Shared underline tab bar — replaces the two near-identical hand-rolled
 * tab strips (Predictive Maintenance's Registry/Readings/History, Admin's
 * Users/Alerts/Freshness/Audit). */
export function Tabs({ items, active, onChange }: { items: TabItem[]; active: string; onChange: (key: string) => void }) {
  return (
    <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--color-border-default)", marginBottom: 18 }}>
      {items.map((item) => {
        const isActive = item.key === active;
        return (
          <button
            key={item.key}
            onClick={() => onChange(item.key)}
            style={{
              font: "inherit",
              fontSize: 13.5,
              fontWeight: isActive ? 700 : 500,
              color: isActive ? "var(--color-primary-700)" : "var(--color-text-secondary)",
              background: "none",
              border: "none",
              borderBottom: isActive ? "2px solid var(--color-primary-600)" : "2px solid transparent",
              padding: "10px 14px",
              marginBottom: -1,
              cursor: "pointer",
            }}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
