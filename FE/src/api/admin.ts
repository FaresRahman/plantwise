import { apiRequest } from "./client";

export interface AdminUser {
  id: number;
  email: string;
  full_name: string;
  role: "admin" | "operator" | "viewer";
  is_verified: boolean;
  is_active: boolean;
}

export interface AlertSetting {
  module: string;
  urgency_threshold: "low" | "med" | "high";
  enabled: boolean;
  recipients: string[];
}

export interface FreshnessRow {
  module: string;
  last_updated_at: string | null;
  expected_cadence_hours: number;
}

export function listAdminUsers() {
  return apiRequest<AdminUser[]>("/admin/users");
}

export function updateUserRole(userId: number, role: string) {
  return apiRequest<AdminUser>(`/admin/users/${userId}/role`, { method: "PATCH", body: { role } });
}

export function setUserActive(userId: number, isActive: boolean) {
  return apiRequest<AdminUser>(`/admin/users/${userId}/active`, { method: "PATCH", body: { is_active: isActive } });
}

export function getFreshnessOverview() {
  return apiRequest<FreshnessRow[]>("/admin/freshness");
}

export function listAlertSettings() {
  return apiRequest<AlertSetting[]>("/notifications/settings");
}

export function updateAlertSetting(module: string, payload: Omit<AlertSetting, "module">) {
  return apiRequest<AlertSetting>(`/notifications/settings/${module}`, { method: "PUT", body: payload });
}

export interface DigestResult {
  sent: boolean;
  reason?: string;
  recipients?: string[];
  total_alerts?: number;
}

export function sendDigestNow() {
  return apiRequest<DigestResult>("/notifications/digest/send", { method: "POST" });
}

export function inviteUser(payload: { email: string; full_name: string; role: string }) {
  return apiRequest<AdminUser>("/auth/invite", { method: "POST", body: payload });
}

export interface BulkInviteEntry {
  email: string;
  full_name?: string | null;
  role?: string | null;
}

export interface BulkInviteError {
  email: string;
  message: string;
}

export interface BulkInviteResult {
  invited: AdminUser[];
  errors: BulkInviteError[];
}

/** Invite several teammates in one submit — full_name is optional per entry
 * (derived from the email on the backend when omitted), so a bulk paste of
 * addresses doesn't need a name typed in for each one. */
export function inviteUsersBulk(payload: { invites: BulkInviteEntry[]; default_role: string }) {
  return apiRequest<BulkInviteResult>("/auth/invite-bulk", { method: "POST", body: payload });
}

export interface AuditLogEntry {
  id: number;
  user_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: string | null;
  created_at: string;
}

export function getAuditLog(limit = 200) {
  return apiRequest<AuditLogEntry[]>(`/admin/audit-log?limit=${limit}`);
}
