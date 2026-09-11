import React from "react";

export type BadgeVariant = "critical" | "warning" | "ok" | "info" | "neutral";

const VARIANT_STYLE: Record<BadgeVariant, { bg: string; fg: string }> = {
  critical: { bg: "var(--color-error-100)", fg: "var(--color-error-700)" },
  warning: { bg: "var(--color-warning-100)", fg: "var(--color-warning-700)" },
  ok: { bg: "var(--color-success-100)", fg: "var(--color-success-700)" },
  info: { bg: "var(--color-info-100)", fg: "var(--color-info-700)" },
  neutral: { bg: "var(--color-neutral-100)", fg: "var(--color-text-secondary)" },
};

/**
 * The one shared pill for every status/urgency/criticality reading in the
 * app (predictive-maintenance urgency, asset criticality, low-stock flags,
 * quality pass/fail, user active/deactivated). Replaces the ~8 independent
 * inline pill implementations that used to exist per module.
 */
export function Badge({ variant, children, dot = false }: { variant: BadgeVariant; children: React.ReactNode; dot?: boolean }) {
  const s = VARIANT_STYLE[variant];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 5,
        fontSize: 12,
        fontWeight: 600,
        height: 32,
        padding: "0 12px",
        minWidth: 90,
        borderRadius: "var(--radius-md)",
        background: s.bg,
        color: s.fg,
        whiteSpace: "nowrap",
      }}
    >
      {dot && <span style={{ width: 5, height: 5, borderRadius: "50%", background: "currentColor", flex: "none" }} />}
      {children}
    </span>
  );
}

/** Maps the app's recurring 3-tier urgency/criticality strings to a Badge
 * variant, so callers don't re-derive this mapping per module. */
export function urgencyVariant(level: string): BadgeVariant {
  const v = level.toLowerCase();
  if (v === "high" || v === "critical") return "critical";
  if (v === "med" || v === "medium" || v === "low-stock" || v === "warning") return "warning";
  if (v === "low") return "info";
  return "neutral";
}
