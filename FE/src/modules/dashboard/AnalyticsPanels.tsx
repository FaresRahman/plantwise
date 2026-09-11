import React from "react";

/** Same dark chip tooltip used across every trend chart in the app — shared
 * from here since this is the one place every module's own trend panel
 * (ProductionPage, InventoryPage, QualityPage) imports its chart chrome
 * from. */
export const DARK_TOOLTIP_STYLE: React.CSSProperties = {
  background: "var(--color-chrome-950)",
  border: "1px solid var(--color-chrome-800)",
  borderRadius: "var(--radius-md)",
  color: "#fff",
  fontSize: 12.5,
  padding: "10px 12px",
};

export const GRANULARITY_OPTIONS = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
] as const;

export function periodLabel(dateStr: string, granularity: "day" | "week" | "month" | "year"): string {
  const d = new Date(dateStr);
  if (granularity === "year") return d.getFullYear().toString();
  if (granularity === "month") return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Colored-dot + label, matching the reference screenshots' legend
 * treatment (a row of dots near the chart title, not recharts' default
 * bottom legend). */
export function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--color-text-secondary)" }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, flex: "none" }} />
      {label}
    </span>
  );
}

/** Shared panel chrome: title/subtitle/legend on the left, pill filters on
 * the right — the layout every reference screenshot uses for its chart
 * cards. */
export function PanelHeader({
  title,
  subtitle,
  legend,
  filters,
}: {
  title: string;
  subtitle?: string;
  legend?: React.ReactNode;
  filters?: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
      <div>
        <div style={{ fontSize: 14, fontWeight: 700 }}>{title}</div>
        {subtitle && <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>{subtitle}</div>}
        {legend && <div style={{ display: "flex", gap: 14, marginTop: 8 }}>{legend}</div>}
      </div>
      {filters && <div style={{ display: "flex", gap: 8 }}>{filters}</div>}
    </div>
  );
}
