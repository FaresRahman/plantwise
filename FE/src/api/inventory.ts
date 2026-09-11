import { apiRequest } from "./client";
import type { ValidationResult } from "./types";

/** Mirrors app/modules/inventory/schemas.py on the backend. */
export interface ItemProjection {
  /** null means no stock-movement rows exist yet — level is unknown, not 0. */
  current_qty: number | null;
  daily_consumption: number;
  days_to_runout: number | null;
  runout_date: string | null;
  is_low: boolean;
  has_data: boolean;
}

export interface Item {
  id: number;
  tenant_id: number;
  sku: string;
  name: string;
  item_type: "raw" | "wip" | "finished";
  unit_of_measure: string;
  reorder_point: number;
  supplier_lead_time_days: number;
  bill_of_materials: Record<string, number> | null;
  created_at: string;
}

export interface ItemWithProjection extends Item {
  projection: ItemProjection;
}

export interface StockMovement {
  id: number;
  item_id: number;
  timestamp: string;
  current_qty: number;
  qty_in: number;
  qty_out: number;
  movement_reason: string | null;
}

export interface ItemInput {
  sku: string;
  name: string;
  item_type: "raw" | "wip" | "finished";
  unit_of_measure: string;
  reorder_point: number;
  supplier_lead_time_days: number;
  bill_of_materials: Record<string, number> | null;
}

export function listItems() {
  return apiRequest<ItemWithProjection[]>("/inventory/items");
}

export function createItem(payload: ItemInput) {
  return apiRequest<Item>("/inventory/items", { method: "POST", body: payload });
}

export function updateItem(id: number, payload: Partial<ItemInput>) {
  return apiRequest<Item>(`/inventory/items/${id}`, { method: "PUT", body: payload });
}

export function deleteItem(id: number) {
  return apiRequest<void>(`/inventory/items/${id}`, { method: "DELETE" });
}

export function getItemHistory(id: number, days = 30) {
  return apiRequest<StockMovement[]>(`/inventory/items/${id}/history?days=${days}`);
}

/** One day's aggregated in/out movement — mirrors service.get_consumption_trend's per-day dict. */
export interface ConsumptionPoint {
  date: string;
  qty_in: number;
  qty_out: number;
}

export function getConsumptionTrend(id: number, days = 30) {
  return apiRequest<ConsumptionPoint[]>(`/inventory/items/${id}/consumption-trend?days=${days}`);
}

/** Single-row alternative to the stock-movements CSV — logging today's
 * current stock without building a CSV for one row. */
export interface StockMovementQuickInput {
  timestamp?: string;
  current_qty: number;
  qty_in?: number;
  qty_out?: number;
  movement_reason?: string | null;
}

export function quickLogStock(itemId: number, payload: StockMovementQuickInput) {
  return apiRequest<StockMovement>(`/inventory/items/${itemId}/stock/quick`, { method: "POST", body: payload });
}

// CSV upload paths for <CsvUploadFlow>, relative to VITE_API_URL (module prefix included).
export const ITEM_CSV_PATHS = {
  templatePath: "/inventory/csv/items/template",
  mapPath: "/inventory/csv/items/map",
  validatePath: "/inventory/csv/items/validate",
  commitPath: "/inventory/csv/items/commit",
};

export const STOCK_MOVEMENTS_CSV_PATHS = {
  templatePath: "/inventory/csv/stock-movements/template",
  mapPath: "/inventory/csv/stock-movements/map",
  validatePath: "/inventory/csv/stock-movements/validate",
  commitPath: "/inventory/csv/stock-movements/commit",
};

export type { ValidationResult };

export interface LoadSampleDataResult {
  items_seeded: string[];
  movements_seeded: number;
  note?: string;
}

export function loadSampleData() {
  return apiRequest<LoadSampleDataResult>("/inventory/load-sample-data", { method: "POST" });
}
