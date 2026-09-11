import { apiRequest } from "./client";

/** Mirrors app/modules/predictive_maintenance/schemas.py */

export interface MetricRange {
  min: number;
  max: number;
  unit: string;
}

export interface ServiceInterval {
  interval_hours: number;
}

export interface Asset {
  id: number;
  tenant_id: number;
  asset_code: string;
  name: string;
  category: string;
  line_area: string;
  criticality: "low" | "med" | "high";
  monitored_metrics: Record<string, MetricRange>;
  service_intervals: Record<string, ServiceInterval>;
  install_date: string | null;
  created_at: string;
}

export interface AssetIn {
  asset_code: string;
  name: string;
  category?: string;
  line_area?: string;
  criticality?: "low" | "med" | "high";
  monitored_metrics?: Record<string, MetricRange>;
  service_intervals?: Record<string, ServiceInterval>;
  install_date?: string | null;
}

export type AssetUpdate = Partial<AssetIn>;

export interface Reading {
  // Populated on the single-reading quick-log/update responses; omitted on
  // the readings-series endpoint used for charting (not addressable there).
  id?: number;
  timestamp: string;
  value: number;
  unit: string;
}

export interface ReadingsSeries {
  asset_id: number;
  metric: string;
  min: number | null;
  max: number | null;
  unit: string | null;
  readings: Reading[];
}

export interface MaintenanceHistoryRecord {
  id: number;
  tenant_id: number;
  asset_id: number;
  date: string;
  type: "preventive" | "corrective";
  description: string;
  downtime_hours: number;
  parts_replaced: string | null;
}

export type RecommendationStatus = "open" | "acknowledged" | "actioned" | "dismissed";
export type Urgency = "low" | "med" | "high";

export interface Recommendation {
  id: number;
  tenant_id: number;
  asset_id: number;
  issue_key: string;
  issue: string;
  evidence: string;
  recommended_action: string;
  urgency: Urgency;
  estimated_window: string;
  status: RecommendationStatus;
  last_alerted_urgency: Urgency | null;
  linked_maintenance_id: number | null;
  created_at: string;
  updated_at: string;
}

const BASE = "/predictive-maintenance";

// --- Assets ---

export function listAssets() {
  return apiRequest<Asset[]>(`${BASE}/assets`);
}

export function createAsset(payload: AssetIn) {
  return apiRequest<Asset>(`${BASE}/assets`, { method: "POST", body: payload });
}

export function updateAsset(id: number, payload: AssetUpdate) {
  return apiRequest<Asset>(`${BASE}/assets/${id}`, { method: "PUT", body: payload });
}

export function deleteAsset(id: number) {
  return apiRequest<void>(`${BASE}/assets/${id}`, { method: "DELETE" });
}

export function getAssetReadings(id: number, metric: string, days = 30) {
  return apiRequest<ReadingsSeries>(
    `${BASE}/assets/${id}/readings?metric=${encodeURIComponent(metric)}&days=${days}`
  );
}

export function getAssetMaintenanceHistory(id: number) {
  return apiRequest<MaintenanceHistoryRecord[]>(`${BASE}/assets/${id}/maintenance-history`);
}

/** Single-row alternative to the sensor-readings CSV — logging one reading
 * right now without building a CSV for one row. */
export interface ReadingQuickInput {
  metric: string;
  value: number;
  unit?: string;
  timestamp?: string;
}

export function quickLogReading(assetId: number, payload: ReadingQuickInput) {
  return apiRequest<Reading>(`${BASE}/assets/${assetId}/readings/quick`, { method: "POST", body: payload });
}

export type ReadingUpdateInput = Partial<ReadingQuickInput>;

export function updateReading(assetId: number, readingId: number, payload: ReadingUpdateInput) {
  return apiRequest<Reading>(`${BASE}/assets/${assetId}/readings/${readingId}`, { method: "PATCH", body: payload });
}

export function deleteReading(assetId: number, readingId: number) {
  return apiRequest<void>(`${BASE}/assets/${assetId}/readings/${readingId}`, { method: "DELETE" });
}

/** Single-row alternative to the maintenance-history CSV — logging one
 * service event right now without building a CSV for one row. */
export interface MaintenanceHistoryQuickInput {
  event_date?: string;
  type: "preventive" | "corrective";
  description?: string;
  downtime_hours?: number;
  parts_replaced?: string | null;
}

export function quickLogMaintenance(assetId: number, payload: MaintenanceHistoryQuickInput) {
  return apiRequest<MaintenanceHistoryRecord>(`${BASE}/assets/${assetId}/maintenance-history/quick`, { method: "POST", body: payload });
}

export type MaintenanceHistoryUpdateInput = Partial<MaintenanceHistoryQuickInput>;

export function updateMaintenanceRecord(assetId: number, recordId: number, payload: MaintenanceHistoryUpdateInput) {
  return apiRequest<MaintenanceHistoryRecord>(`${BASE}/assets/${assetId}/maintenance-history/${recordId}`, { method: "PATCH", body: payload });
}

export function deleteMaintenanceRecord(assetId: number, recordId: number) {
  return apiRequest<void>(`${BASE}/assets/${assetId}/maintenance-history/${recordId}`, { method: "DELETE" });
}

// --- Recommendations ---

export function listRecommendations(params: { status?: string; urgency?: string } = {}) {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.urgency) query.set("urgency", params.urgency);
  const qs = query.toString();
  return apiRequest<Recommendation[]>(`${BASE}/recommendations${qs ? `?${qs}` : ""}`);
}

export function acknowledgeRecommendation(id: number) {
  return apiRequest<Recommendation>(`${BASE}/recommendations/${id}/acknowledge`, { method: "POST" });
}

export function actionRecommendation(id: number, maintenanceHistoryId: number) {
  return apiRequest<Recommendation>(`${BASE}/recommendations/${id}/action`, {
    method: "POST",
    body: { maintenance_history_id: maintenanceHistoryId },
  });
}

export function dismissRecommendation(id: number) {
  return apiRequest<Recommendation>(`${BASE}/recommendations/${id}/dismiss`, { method: "POST" });
}

export function recomputeRecommendations() {
  return apiRequest<{ status: string }>(`${BASE}/recompute`, { method: "POST" });
}

/** Mirrors service.get_recommendation_stats — PRD §5.7 "recommendation
 * outcomes... feeds the precision metric" analytics. */
export interface RecommendationStats {
  total: number;
  by_status: Record<string, number>;
  by_urgency: Record<string, number>;
}

export function getRecommendationStats() {
  return apiRequest<RecommendationStats>(`${BASE}/recommendations/stats`);
}

export type TrendGranularity = "day" | "week" | "month" | "year";

export interface RecommendationTrendPoint {
  period: string;
  low: number;
  med: number;
  high: number;
  total: number;
}

export function getRecommendationTrend(granularity: TrendGranularity, urgency?: Urgency) {
  const query = new URLSearchParams({ granularity });
  if (urgency) query.set("urgency", urgency);
  return apiRequest<RecommendationTrendPoint[]>(`${BASE}/recommendations/trend?${query.toString()}`);
}

// --- CSV upload paths (consumed directly by <CsvUploadFlow>, which does its
// own authed fetch/multipart handling — these are just the module-relative
// paths it needs) ---

export const ASSET_CSV_PATHS = {
  template: `${BASE}/csv/assets/template`,
  map: `${BASE}/csv/assets/map`,
  validate: `${BASE}/csv/assets/validate`,
  commit: `${BASE}/csv/assets/commit`,
};

export const READINGS_CSV_PATHS = {
  template: `${BASE}/csv/readings/template`,
  map: `${BASE}/csv/readings/map`,
  validate: `${BASE}/csv/readings/validate`,
  commit: `${BASE}/csv/readings/commit`,
};

export const MAINTENANCE_CSV_PATHS = {
  template: `${BASE}/csv/maintenance-history/template`,
  map: `${BASE}/csv/maintenance-history/map`,
  validate: `${BASE}/csv/maintenance-history/validate`,
  commit: `${BASE}/csv/maintenance-history/commit`,
};

export const METRIC_RANGE_CSV_PATHS = {
  template: `${BASE}/csv/metric-ranges/template`,
  map: `${BASE}/csv/metric-ranges/map`,
  validate: `${BASE}/csv/metric-ranges/validate`,
  commit: `${BASE}/csv/metric-ranges/commit`,
};

/** Single-row alternative to the metric-ranges CSV — sets (or replaces) one
 * metric's normal range on this asset without building a CSV for one row. */
export interface MetricRangeQuickInput {
  metric_name: string;
  min: number;
  max: number;
  unit?: string;
}

export function quickSetMetricRange(assetId: number, payload: MetricRangeQuickInput) {
  return apiRequest<Asset>(`${BASE}/assets/${assetId}/metric-ranges/quick`, { method: "POST", body: payload });
}

export interface LoadSampleDataResult {
  assets_seeded: string[];
  readings_seeded: number;
  maintenance_records_seeded: number;
  note?: string;
}

export function loadSampleData() {
  return apiRequest<LoadSampleDataResult>(`${BASE}/load-sample-data`, { method: "POST" });
}
