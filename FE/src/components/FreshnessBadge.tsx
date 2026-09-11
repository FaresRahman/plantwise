import React from "react";

// BRD §4.7: "stale data ... is flagged amber/red." Past the cadence it's
// amber; well past it (severely overdue) it escalates to red.
const SEVERE_STALE_MULTIPLIER = 3;

function hoursSince(iso: string | null): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / (1000 * 60 * 60);
}

/**
 * Freshness indicator — the PRD's "core trust feature": every card must
 * show how current its data is. `isStale` should come from the backend (it
 * knows the module's expected cadence); `expectedCadenceHours` (also from
 * the backend) lets this component distinguish "a bit stale" from "badly
 * overdue" instead of a single stale/fresh boolean. `compact` shortens the
 * label ("2h ago" instead of "Updated 2h ago") for tight spaces like a
 * dashboard card's corner.
 */
export function FreshnessBadge({
  lastUpdatedAt,
  isStale,
  expectedCadenceHours,
  compact = false,
}: {
  lastUpdatedAt: string | null;
  isStale: boolean;
  expectedCadenceHours?: number | null;
  compact?: boolean;
}) {
  const hours = hoursSince(lastUpdatedAt);

  const severelyStale =
    isStale && hours !== null && !!expectedCadenceHours && hours > expectedCadenceHours * SEVERE_STALE_MULTIPLIER;

  const state: "none" | "fresh" | "aging" | "stale" = !lastUpdatedAt
    ? "none"
    : severelyStale
      ? "stale"
      : isStale
        ? "aging"
        : "fresh";

  const label = compact
    ? hours === null
      ? "no data"
      : hours < 1
        ? "just now"
        : hours < 48
          ? `${Math.round(hours)}h ago`
          : `${Math.round(hours / 24)}d ago`
    : hours === null
      ? "No data yet"
      : hours < 1
        ? "Updated just now"
        : `Updated ${Math.round(hours)}h ago`;
  const color =
    state === "none"
      ? "var(--color-text-tertiary)"
      : state === "stale"
        ? "var(--color-error-700)"
        : state === "aging"
          ? "var(--color-warning-700)"
          : "var(--color-success-700)";
  const dot =
    state === "none"
      ? "var(--color-neutral-300)"
      : state === "stale"
        ? "var(--color-error-500)"
        : state === "aging"
          ? "var(--color-warning-500)"
          : "var(--color-success-500)";

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 700, color }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: dot, flex: "none" }} />
      <span className="num">{label}</span>
      {isStale && lastUpdatedAt && (severelyStale ? " · overdue" : " · stale")}
    </span>
  );
}
