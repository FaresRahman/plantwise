import { apiRequest } from "./client";

/** Mirrors app/core/contracts.py:ModuleSummary on the backend. */
export interface ModuleSummary {
  module: string;
  title: string;
  status: "ok" | "warning" | "critical";
  headline: string;
  metrics: Array<{ label: string; value: string }>;
  last_updated_at: string | null;
  is_stale: boolean;
  /** null when this module has no per-tenant cadence configured yet. */
  expected_cadence_hours: number | null;
  /** null means "no data to evaluate yet" (distinct from a confirmed 0) —
   * the type previously claimed this was always a number while the backend
   * (core/contracts.py:ModuleSummary) already sends null for that case. */
  alerts_count: number | null;
  drilldown_path: string;
}

export function getDashboardSummary() {
  return apiRequest<ModuleSummary[]>("/dashboard/summary");
}
