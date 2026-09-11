import { apiRequest } from "./client";

/** Mirrors app/modules/production/schemas.py:LineOut on the backend. */
export interface Line {
  id: number;
  tenant_id: number;
  line_code: string;
  name: string;
  stations: string[];
  products: string[];
  shift_target_units: number;
  ideal_cycle_time_seconds: number;
  created_at: string;
}

/** Mirrors LineCreate/LineBase — used for both create and full-form edit. */
export interface LineInput {
  line_code: string;
  name: string;
  stations: string[];
  products: string[];
  shift_target_units: number;
  ideal_cycle_time_seconds: number;
}

export interface DowntimeParetoEntry {
  station_id: string;
  downtime_reason: string;
  downtime_minutes: number;
}

/** Mirrors engine.compute_line_metrics's return dict. Ratios (availability/
 * performance/quality/oee) are 0..1 — multiply by 100 to display as percent.
 */
export interface LineMetrics {
  line_id: number;
  line_code: string;
  line_name: string;
  planned_time_minutes: number;
  downtime_minutes: number;
  run_time_minutes: number;
  total_units: number;
  good_units: number;
  reject_units: number;
  availability: number;
  performance: number;
  quality: number;
  oee: number;
  shift_target_units: number;
  gap_to_target: number;
  downtime_pareto: DowntimeParetoEntry[];
  /** False means no output has been logged for this window yet — the
   * figures above are zero by absence of data, not a real reading. */
  has_data: boolean;
}

/** Mirrors engine.get_downtime_events's per-event dict exactly. */
export interface DowntimeEvent {
  line_id: string;
  station_id: string;
  downtime_reason: string | null;
  timestamp: string;
  downtime_minutes: number;
}

function windowQuery(start?: string, end?: string): string {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function getLines() {
  return apiRequest<Line[]>("/production/lines");
}

export function createLine(payload: LineInput) {
  return apiRequest<Line>("/production/lines", { method: "POST", body: payload });
}

export function updateLine(id: number, payload: Partial<LineInput>) {
  return apiRequest<Line>(`/production/lines/${id}`, { method: "PUT", body: payload });
}

export function deleteLine(id: number) {
  return apiRequest<void>(`/production/lines/${id}`, { method: "DELETE" });
}

export function getLineMetrics(id: number, start?: string, end?: string) {
  return apiRequest<LineMetrics>(`/production/lines/${id}/metrics${windowQuery(start, end)}`);
}

export function getLineDowntimeEvents(id: number, start?: string, end?: string) {
  return apiRequest<DowntimeEvent[]>(`/production/lines/${id}/downtime-events${windowQuery(start, end)}`);
}

/** One day's OEE point — mirrors engine.compute_oee_history's per-day dict. */
export interface OeeHistoryPoint {
  date: string;
  oee: number;
  availability: number;
  performance: number;
  quality: number;
  total_units: number;
  shift_target_units: number;
}

export function getLineOeeHistory(id: number, days = 14) {
  return apiRequest<OeeHistoryPoint[]>(`/production/lines/${id}/oee-history?days=${days}`);
}

/** Single-row alternative to the output-logs CSV — logging one station's
 * numbers for right now without building a CSV for one row. */
export interface OutputLogQuickInput {
  station_id: string;
  timestamp?: string;
  units_produced?: number;
  units_good?: number;
  units_reject?: number;
  run_state?: "run" | "idle" | "stop";
  downtime_minutes?: number;
  downtime_reason?: string | null;
}

export interface OutputLog {
  id: number;
  line_id: number;
  station_id: string;
  timestamp: string;
  units_produced: number;
  units_good: number;
  units_reject: number;
  run_state: string;
  downtime_minutes: number;
  downtime_reason: string | null;
}

export function quickLogOutput(lineId: number, payload: OutputLogQuickInput) {
  return apiRequest<OutputLog>(`/production/lines/${lineId}/output-logs/quick`, { method: "POST", body: payload });
}

export interface LoadSampleDataResult {
  lines_seeded: string[];
  output_logs_seeded: number;
  note?: string;
}

/** CSV upload paths for the onboarding wizard and module page to share
 *  — keeps the three-step pattern (template / validate / commit) in one
 *  place so the wizard and the full module page stay in sync. */
export const LINE_CSV_PATHS = {
  templatePath: "/production/csv/lines/template",
  mapPath: "/production/csv/lines/map",
  validatePath: "/production/csv/lines/validate",
  commitPath: "/production/csv/lines/commit",
};

export const OUTPUT_LOG_CSV_PATHS = {
  templatePath: "/production/csv/output-logs/template",
  mapPath: "/production/csv/output-logs/map",
  validatePath: "/production/csv/output-logs/validate",
  commitPath: "/production/csv/output-logs/commit",
};

export function loadSampleData() {
  return apiRequest<LoadSampleDataResult>("/production/load-sample-data", { method: "POST" });
}
