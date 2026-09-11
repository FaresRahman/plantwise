import { apiRequest, BASE_URL, getToken, ApiError } from "./client";
import type { ColumnMeta, CommitResult, MappingResult, ValidationResult } from "./types";

/** Mirrors app/modules/db_import/schemas.py */

export interface DbConnectionInput {
  connection_id?: number | null;
  engine?: string | null;
  host?: string | null;
  port?: number | null;
  database?: string | null;
  username?: string | null;
  password?: string | null;
  ssl?: boolean;
  /** Set to persist this connection (encrypted) under this name after a
   * successful test — the opt-in "Persistent Connection" mode. Omitted =
   * one-time import, nothing stored server-side. */
  save_as?: string | null;
}

export interface TestConnectionResult {
  detected: string[];
  version: string | null;
  ambiguous: boolean;
  saved_connection_id: number | null;
}

export interface SavedConnection {
  id: number;
  name: string;
  engine: string;
  host: string;
  port: number;
  database: string | null;
  username: string;
  ssl: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface SupportedEngine {
  engine: string;
  display_name: string;
  tier: 1 | 2;
  prerequisite_note: string | null;
  local_only: boolean;
}

export interface ImportableEntity {
  key: string;
  label: string;
}

export interface DiscoveredTable {
  schema_name: string | null;
  name: string;
  row_count_estimate: number | null;
  recommendation_score: number;
  recommendation_reason: string | null;
}

const BASE = "/db-import";

export function listEngines() {
  return apiRequest<SupportedEngine[]>(`${BASE}/engines`);
}

export function listImportableEntities() {
  return apiRequest<ImportableEntity[]>(`${BASE}/entities`);
}

export function testConnection(payload: DbConnectionInput) {
  return apiRequest<TestConnectionResult>(`${BASE}/test-connection`, { method: "POST", body: payload });
}

export function listSavedConnections() {
  return apiRequest<SavedConnection[]>(`${BASE}/connections`);
}

export function deleteSavedConnection(id: number) {
  return apiRequest<void>(`${BASE}/connections/${id}`, { method: "DELETE" });
}

export function listSchemas(connection: DbConnectionInput) {
  return apiRequest<{ schemas: string[] }>(`${BASE}/schemas`, { method: "POST", body: connection });
}

export function listTables(entity: string, connection: DbConnectionInput, schemaName?: string | null) {
  return apiRequest<DiscoveredTable[]>(`${BASE}/${entity}/tables`, {
    method: "POST",
    body: { connection, schema_name: schemaName ?? null },
  });
}

export function sampleTable(connection: DbConnectionInput, schemaName: string | null, table: string, limit = 25) {
  return apiRequest<{ rows: Record<string, unknown>[] }>(`${BASE}/sample`, {
    method: "POST",
    body: { connection, schema_name: schemaName, table, limit },
  });
}

export function mapTableColumns(entity: string, connection: DbConnectionInput, schemaName: string | null, table: string) {
  return apiRequest<MappingResult>(`${BASE}/${entity}/map`, {
    method: "POST",
    body: { connection, schema_name: schemaName, table },
  });
}

export function validateTable(
  entity: string,
  connection: DbConnectionInput,
  schemaName: string | null,
  table: string,
  mapping: Record<string, string | null> | null
) {
  return apiRequest<ValidationResult>(`${BASE}/${entity}/validate`, {
    method: "POST",
    body: { connection, schema_name: schemaName, table, mapping },
  });
}

export function commitTableImport(entity: string, editedRows: Record<string, unknown>[], skipInvalid = true) {
  return apiRequest<CommitResult>(`${BASE}/${entity}/commit`, {
    method: "POST",
    body: { edited_rows: editedRows, skip_invalid: skipInvalid },
  });
}

// --- Local Connector registration/auth (management UI only — the
// connector application itself is a separate installable download) ---

export interface Connector {
  id: number;
  name: string;
  status: "pending" | "active" | "revoked";
  created_at: string;
  registered_at: string | null;
  last_seen_at: string | null;
}

export function listConnectors() {
  return apiRequest<Connector[]>(`${BASE}/connectors`);
}

export function createConnector(name: string) {
  return apiRequest<{ connector_id: number; name: string; registration_key: string }>(`${BASE}/connectors`, {
    method: "POST",
    body: { name },
  });
}

export function revokeConnector(id: number) {
  return apiRequest<void>(`${BASE}/connectors/${id}`, { method: "DELETE" });
}

/** apiRequest always parses JSON, so the installer download (a raw binary)
 * needs its own fetch — same auth header, but saved as a file instead. */
export async function downloadConnectorInstaller(): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BASE_URL}${BASE}/connectors/download`, { headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ?? detail;
    } catch {
      // not JSON — keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "PlantwiseConnector.exe";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// --- Continuous sync — a saved mapping re-run on a timer instead of once
// by hand. Only ever available once a connection is saved (connection_id
// set) since a one-time connection's credentials aren't kept anywhere to
// reuse on the next tick. Customers who never set one of these up keep
// using manual entry / CSV upload exactly as before. ---

export interface SyncSchedule {
  id: number;
  entity: string;
  connection_id: number | null;
  connector_id: number | null;
  schema_name: string | null;
  table_name: string;
  column_mapping: Record<string, string>;
  watermark_column: string;
  interval_minutes: number;
  enabled: boolean;
  last_synced_at: string | null;
  last_status: string | null;
  last_error: string | null;
  consecutive_failures: number;
  created_at: string;
}

export function listSyncSchedules() {
  return apiRequest<SyncSchedule[]>(`${BASE}/sync-schedules`);
}

export function createSyncSchedule(payload: {
  entity: string;
  connection_id?: number | null;
  connector_id?: number | null;
  schema_name: string | null;
  table: string;
  column_mapping: Record<string, string>;
  watermark_column: string;
  interval_minutes: number;
}) {
  return apiRequest<SyncSchedule>(`${BASE}/sync-schedules`, { method: "POST", body: payload });
}

export function setSyncScheduleEnabled(id: number, enabled: boolean) {
  return apiRequest<SyncSchedule>(`${BASE}/sync-schedules/${id}`, { method: "PATCH", body: { enabled } });
}

export function deleteSyncSchedule(id: number) {
  return apiRequest<void>(`${BASE}/sync-schedules/${id}`, { method: "DELETE" });
}

export type { ColumnMeta, MappingResult, ValidationResult, CommitResult };
