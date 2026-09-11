import React from "react";
import { useNavigate } from "react-router-dom";
import { BadgeCheck, BookOpen, Boxes, ClipboardList, Factory, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { ModuleSummary } from "../api/dashboard";
import { FreshnessBadge } from "./FreshnessBadge";

const MODULE_ICON: Record<string, LucideIcon> = {
  predictive_maintenance: Wrench,
  production: Factory,
  inventory: Boxes,
  quality: BadgeCheck,
  sop: BookOpen,
  shift_reports: ClipboardList,
};

/** Icon-badge tint per status, for the non-critical cards — critical
 * already gets the dark "featured" treatment below; ok/warning previously
 * looked identical apart from the freshness corner, so a module's health
 * wasn't readable at a glance across the row. Built from the same
 * success/warning tint tokens the rest of the app already uses for status. */
const STATUS_TINT: Record<ModuleSummary["status"], { bg: string; fg: string }> = {
  ok: { bg: "var(--color-success-50)", fg: "var(--color-success-700)" },
  warning: { bg: "var(--color-warning-50)", fg: "var(--color-warning-700)" },
  critical: { bg: "var(--color-error-50)", fg: "var(--color-error-700)" },
};

/**
 * One dashboard module card. The whole card is the click target (no
 * separate "drill in" link) — a border/lift on hover is the only affordance
 * needed. Status reads through the icon tint and a plain-language headline;
 * freshness is a small corner readout, not a decoration. A critical module
 * also gets a left accent bar + tinted background, so it reads as different
 * across a row of cards at a glance, not just via a small icon color.
 * Secondary metrics (beyond the headline number) render inside the card as
 * a hairline-divided spec row, not as a separate element bolted on outside it.
 */
export function Card({ summary, readonly }: { summary: ModuleSummary; readonly?: boolean }) {
  const navigate = useNavigate();
  const [primaryMetric, ...secondaryMetrics] = summary.metrics;
  // `readonly` (passed for Viewers) used to also block drill-down, but the
  // persona table explicitly grants Viewers "view dashboards" and the PRD's
  // drill-down requirement isn't scoped to non-Viewers — read-only means no
  // actions/config on the destination page (already enforced there via
  // RoleGuard), not "can't navigate to it." Kept as a prop in case a future
  // read-only-specific affordance needs it.
  const canClick = !!summary.drilldown_path;
  const Icon = MODULE_ICON[summary.module] ?? Wrench;
  const tint = STATUS_TINT[summary.status];
  // A critical module needs to read as different at a glance across a row
  // of otherwise-identical cards, not just via a small icon tint — same
  // left-accent-bar language the dashboard's own top alert banner uses.
  const isCritical = summary.status === "critical";

  return (
    <div
      className="pw-plate surface"
      style={{
        padding: 18,
        cursor: canClick ? "pointer" : "default",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        borderLeft: isCritical ? "3px solid var(--color-error-600)" : undefined,
        background: isCritical ? "var(--color-error-50)" : undefined,
      }}
      onClick={canClick ? () => navigate(summary.drilldown_path) : undefined}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, minWidth: 0 }}>
          <span
            style={{
              width: 30,
              height: 30,
              borderRadius: "var(--radius-md)",
              background: tint.bg,
              color: tint.fg,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flex: "none",
            }}
          >
            <Icon size={15} strokeWidth={1.8} />
          </span>
          <span style={{ fontSize: 13.5, fontWeight: 700, color: "var(--color-text-primary)" }}>{summary.title}</span>
        </div>
        <FreshnessBadge
          compact
          lastUpdatedAt={summary.last_updated_at}
          isStale={summary.is_stale}
          expectedCadenceHours={summary.expected_cadence_hours}
        />
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span className="num" style={{ fontSize: 26, fontWeight: 700, lineHeight: 1, color: "var(--color-text-primary)" }}>
          {primaryMetric?.value ?? "-"}
        </span>
        <span style={{ fontSize: 12.5, color: "var(--color-text-tertiary)" }}>{primaryMetric?.label ?? ""}</span>
      </div>

      <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>{summary.headline}</div>

      {secondaryMetrics.length > 0 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "6px 16px",
            paddingTop: 12,
            marginTop: 2,
            borderTop: "1px solid var(--color-border-subtle)",
          }}
        >
          {secondaryMetrics.map((m) => (
            <div key={m.label} style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              <span className="num" style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)" }}>
                {m.value}
              </span>
              <span style={{ fontSize: 10.5, color: "var(--color-text-tertiary)" }}>{m.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
