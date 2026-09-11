import { apiRequest } from "./client";
import type { ValidationResult } from "./types";

/** Mirrors app/modules/quality/models.py:Characteristic. */
export interface Characteristic {
  id: number;
  tenant_id: number;
  part_id: string;
  characteristic_name: string;
  nominal_value: number;
  tolerance: number;
  inspection_type: string;
  line_id: string;
  station_id: string;
  defect_categories: string[];
  created_at: string;
}

export interface CharacteristicIn {
  part_id: string;
  characteristic_name: string;
  nominal_value: number;
  tolerance: number;
  inspection_type: string;
  line_id: string;
  station_id: string;
  defect_categories: string[];
}

/** Mirrors app/modules/quality/schemas.py:DefectBreakdownItem. `pct_of_failures` is already 0-100. */
export interface DefectBreakdownItem {
  defect_type: string | null;
  count: number;
  pct_of_failures: number;
}

/** Mirrors app/modules/quality/schemas.py:ToleranceDrift. `*_limit_fraction` is
 * |measured - nominal| / tolerance — 1.0 means right at the tolerance limit. */
export interface ToleranceDrift {
  recent_avg_measured: number | null;
  baseline_avg_measured: number | null;
  recent_limit_fraction: number | null;
  baseline_limit_fraction: number | null;
  is_drifting_toward_limit: boolean;
  is_approaching_limit: boolean;
}

/**
 * Mirrors app/modules/quality/schemas.py:CharacteristicTrendOut.
 * `recent_rate` / `baseline_rate` are 0-1 fractions — multiply by 100 to display as a percentage.
 */
export interface CharacteristicTrend {
  characteristic_id: number;
  part_id: string;
  characteristic_name: string;
  recent_total: number;
  recent_fail: number;
  recent_rate: number;
  baseline_total: number;
  baseline_fail: number;
  baseline_rate: number;
  is_spike: boolean;
  defect_breakdown: DefectBreakdownItem[];
  root_cause: string | null;
  tolerance_drift: ToleranceDrift | null;
}

export function getCharacteristics() {
  return apiRequest<Characteristic[]>("/quality/characteristics");
}

export function createCharacteristic(payload: CharacteristicIn) {
  return apiRequest<Characteristic>("/quality/characteristics", { method: "POST", body: payload });
}

export function updateCharacteristic(id: number, payload: CharacteristicIn) {
  return apiRequest<Characteristic>(`/quality/characteristics/${id}`, { method: "PUT", body: payload });
}

export function deleteCharacteristic(id: number) {
  return apiRequest<void>(`/quality/characteristics/${id}`, { method: "DELETE" });
}

export function getCharacteristicTrend(id: number) {
  return apiRequest<CharacteristicTrend>(`/quality/characteristics/${id}/trend`);
}

/** Raw measured values over time for one characteristic — distinct from
 * getCharacteristicTrend's pass/fail rate comparison. */
export interface Measurement {
  timestamp: string;
  measured_value: number;
  pass_fail: boolean;
}

export function getCharacteristicMeasurements(id: number, days = 30) {
  return apiRequest<Measurement[]>(`/quality/characteristics/${id}/measurements?days=${days}`);
}

/** Single-row alternative to the inspection-records CSV — logging one
 * inspection result without building a CSV for one row. */
export interface InspectionQuickInput {
  measured_value: number;
  pass_fail: boolean;
  defect_type?: string | null;
  station_id?: string | null;
  inspector?: string;
  timestamp?: string;
}

export interface InspectionRecord {
  id: number;
  part_id: string;
  timestamp: string;
  characteristic_name: string;
  measured_value: number;
  pass_fail: boolean;
  defect_type: string | null;
  line_id: string;
  station_id: string;
  inspector: string;
}

export function quickLogInspection(characteristicId: number, payload: InspectionQuickInput) {
  return apiRequest<InspectionRecord>(`/quality/characteristics/${characteristicId}/inspections/quick`, {
    method: "POST",
    body: payload,
  });
}

// CSV upload flow paths (module-relative, for <CsvUploadFlow>) — auth header
// and multipart handling is done inside that shared component, not here.
export const CHARACTERISTIC_CSV_PATHS = {
  templatePath: "/quality/csv/characteristics/template",
  mapPath: "/quality/csv/characteristics/map",
  validatePath: "/quality/csv/characteristics/validate",
  commitPath: "/quality/csv/characteristics/commit",
};

export const INSPECTION_RECORDS_CSV_PATHS = {
  templatePath: "/quality/csv/inspection-records/template",
  mapPath: "/quality/csv/inspection-records/map",
  validatePath: "/quality/csv/inspection-records/validate",
  commitPath: "/quality/csv/inspection-records/commit",
};

// Re-exported for convenience so callers don't need a second import for the
// shared ValidationResult shape used by the CSV flow.
export type { ValidationResult };

export interface LoadSampleDataResult {
  characteristics_seeded: string[];
  inspection_records_seeded: number;
  note?: string;
}

export function loadSampleData() {
  return apiRequest<LoadSampleDataResult>("/quality/load-sample-data", { method: "POST" });
}

/** Mirrors app/modules/quality/schemas.py:QualityHoldOut. */
export interface QualityHold {
  id: number;
  tenant_id: number;
  part_id: string;
  lot_number: string;
  reason: string;
  status: "open" | "released";
  created_by: number;
  created_at: string;
  released_at: string | null;
  released_by: number | null;
  release_note: string | null;
}

export interface QualityHoldIn {
  part_id: string;
  lot_number: string;
  reason: string;
}

export function getHolds(status?: "open" | "released") {
  return apiRequest<QualityHold[]>(`/quality/holds${status ? `?hold_status=${status}` : ""}`);
}

export function createHold(payload: QualityHoldIn) {
  return apiRequest<QualityHold>("/quality/holds", { method: "POST", body: payload });
}

/** release_note is required — mirrors the reason required to open a hold in
 * the first place, so there's always a record of why a held lot was safe
 * to ship. */
export function releaseHold(id: number, releaseNote: string) {
  return apiRequest<QualityHold>(`/quality/holds/${id}/release`, { method: "POST", body: { release_note: releaseNote } });
}
