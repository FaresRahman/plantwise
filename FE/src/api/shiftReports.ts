import { apiRequest, BASE_URL, getToken } from "./client";

const API_BASE = BASE_URL;
const MODULE_BASE = "/shift-reports";

// CSV upload paths for <CsvUploadFlow>
export const SCHEDULE_CSV_PATHS = {
  templatePath: `${MODULE_BASE}/csv/schedules/template`,
  mapPath: `${MODULE_BASE}/csv/schedules/map`,
  validatePath: `${MODULE_BASE}/csv/schedules/validate`,
  commitPath: `${MODULE_BASE}/csv/schedules/commit`,
};

export interface ShiftSchedule {
  id: number;
  name: string;
  start_time: string;
  end_time: string;
  areas: string[];
  recipients: string[];
}

export interface ShiftContribution {
  module: string;
  summary_text: string;
  data: Record<string, unknown>;
  open_items: string[];
}

export interface ShiftReport {
  id: number;
  shift_schedule_id: number | null;
  window_start: string;
  window_end: string;
  compiled_content: ShiftContribution[];
  next_shift_actions: string[];
  created_at: string;
}

export function listShiftSchedules() {
  return apiRequest<ShiftSchedule[]>("/shift-reports/schedules");
}

export function createShiftSchedule(payload: Omit<ShiftSchedule, "id">) {
  return apiRequest<ShiftSchedule>("/shift-reports/schedules", { method: "POST", body: payload });
}

export function deleteShiftSchedule(id: number) {
  return apiRequest<void>(`/shift-reports/schedules/${id}`, { method: "DELETE" });
}

export function generateShiftReport(shiftScheduleId: number) {
  return apiRequest<ShiftReport>("/shift-reports/generate", {
    method: "POST",
    body: { shift_schedule_id: shiftScheduleId },
  });
}

export function listShiftReports() {
  return apiRequest<ShiftReport[]>("/shift-reports");
}

/** Downloads the exportable archive file (§5.7) for one report — a plain
 * request, not apiRequest, since the response is a file, not JSON. */
export async function exportShiftReport(id: number, windowStart: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/shift-reports/${id}/export`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) throw new Error("Failed to export report");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `shift-report-${windowStart.slice(0, 16).replace(/[:T]/g, "-")}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}
