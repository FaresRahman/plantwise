import React, { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import {
  AdminUser,
  AlertSetting,
  AuditLogEntry,
  FreshnessRow,
  getAuditLog,
  getFreshnessOverview,
  inviteUser,
  listAdminUsers,
  listAlertSettings,
  sendDigestNow,
  setUserActive,
  updateAlertSetting,
  updateUserRole,
} from "../../api/admin";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { Skeleton } from "../../components/Loading";
import { ModuleIcon, PageHeader } from "../../components/PageHeader";
import { Select } from "../../components/Select";
import { Table, TBody, Td, Th, THead, Tr } from "../../components/Table";
import { Tabs } from "../../components/Tabs";
import { BulkInviteForm } from "../_shared/BulkInviteForm";
import { DataSourceSetup } from "../_shared/DataSourceSetup";
import { QuickField } from "../_shared/QuickLogForm";

const ROLES = ["admin", "operator", "viewer"] as const;
const ROLE_OPTIONS = ROLES.map((r) => ({ value: r, label: r[0].toUpperCase() + r.slice(1) }));
const URGENCY_LEVELS = ["low", "med", "high"] as const;
const URGENCY_OPTIONS = URGENCY_LEVELS.map((u) => ({ value: u, label: u === "med" ? "Medium" : u[0].toUpperCase() + u.slice(1) }));

function UsersTab() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<string>("");
  const [bulkMode, setBulkMode] = useState(false);

  function refresh() {
    listAdminUsers().then(setUsers);
  }
  useEffect(refresh, []);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!role) return;
    await inviteUser({ email, full_name: fullName, role });
    setEmail("");
    setFullName("");
    setRole("");
    refresh();
  }

  return (
    <div>
      <div className="surface" style={{ padding: 20, marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 15, fontFamily: "var(--font-family-display)", fontWeight: 700 }}>
              {bulkMode ? "Invite Several Teammates" : "Invite a Teammate"}
            </div>
            <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginTop: 3, lineHeight: 1.6 }}>
              {bulkMode
                ? "Paste a list of email addresses to invite them all at once."
                : "Add one teammate and assign their role."}
            </div>
          </div>
          <button type="button" className="btn-secondary" onClick={() => setBulkMode((v) => !v)}>
            {bulkMode ? "Invite One at a Time" : "Invite Several at Once"}
          </button>
        </div>
        {bulkMode ? (
          <BulkInviteForm roles={ROLES} onInvited={refresh} />
        ) : (
          <form onSubmit={handleInvite}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 }}>
              <QuickField label="Full Name">
                <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Jordan Lee" required />
              </QuickField>
              <QuickField label="Email">
                <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" required />
              </QuickField>
              <QuickField label="Role">
                <Select value={role} onChange={(e) => setRole(e.target.value)} options={ROLE_OPTIONS} placeholder="Select role" />
              </QuickField>
            </div>
            <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
              <button type="submit" className="btn-primary" disabled={!role}>Invite Teammate</button>
            </div>
          </form>
        )}
      </div>

      {!users && <Skeleton rows={4} height={32} />}
      {users && users.length === 0 && (
        <EmptyState title="No users yet" message="Invite a teammate above to get started." />
      )}
      {users && users.length > 0 && (
        <Table>
          <THead>
            <Tr>
              <Th>Name</Th>
              <Th>Email</Th>
              <Th align="center">Role</Th>
              <Th align="center">Status</Th>
              <Th align="right">Actions</Th>
            </Tr>
          </THead>
          <TBody>
            {users.map((u) => (
              <Tr key={u.id}>
                <Td>
                  <span style={{ fontWeight: 600 }}>{u.full_name}</span>
                </Td>
                <Td>
                  <span style={{ color: "var(--color-text-secondary)" }}>{u.email}</span>
                </Td>
                <Td align="center">
                  <Select
                    compact
                    value={u.role}
                    onChange={(e) => updateUserRole(u.id, e.target.value).then(refresh)}
                    options={ROLE_OPTIONS}
                    style={{ width: 130, margin: "0 auto" }}
                  />
                </Td>
                <Td align="center">
                  <Badge variant={u.is_active ? "ok" : "neutral"}>{u.is_active ? "Active" : "Deactivated"}</Badge>
                </Td>
                <Td align="right">
                  <button
                    onClick={() => setUserActive(u.id, !u.is_active).then(refresh)}
                    className={u.is_active ? "btn-danger btn-compact" : "btn-secondary btn-compact"}
                  >
                    {u.is_active ? "Deactivate" : "Reactivate"}
                  </button>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}

/** Minimal, file-scoped notification for transient feedback on the "Send
 * Daily Digest Now" action (e.g. the prerequisite-not-met message) — there's
 * no shared toast component in the app yet, so this is a small fixed-position
 * div rather than pulling in a new dependency. Top-right, gold-accent (the
 * same accent-600 used for the AI gradient CTA and the active nav item, not
 * a one-off color), auto-dismisses on its own timer but can also be closed
 * early via the X button. Entrance animation is gated behind
 * `prefers-reduced-motion: no-preference`; the auto-dismiss itself is a
 * plain timeout so it still disappears on schedule even with reduced motion. */
function AdminToast({ toast, onClose }: { toast: { id: number; message: React.ReactNode } | null; onClose: () => void }) {
  if (!toast) return null;
  return (
    <div
      key={toast.id}
      role="status"
      className="pw-admin-toast"
      style={{
        position: "fixed",
        top: 76, // just below AppShell's 60px topbar, not overlapping it
        right: 24,
        maxWidth: 360,
        background: "var(--color-accent-600)",
        color: "var(--color-accent-ink)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-lg)",
        padding: "14px 16px",
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        fontSize: 13,
        fontWeight: 600,
        lineHeight: 1.5,
        zIndex: 1000,
      }}
    >
      <span style={{ flex: 1 }}>{toast.message}</span>
      <button
        onClick={onClose}
        aria-label="Dismiss notification"
        style={{
          flex: "none",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 20,
          height: 20,
          border: "none",
          borderRadius: "50%",
          background: "rgba(20, 17, 10, 0.14)",
          color: "inherit",
          cursor: "pointer",
        }}
      >
        <X size={12} strokeWidth={2.4} />
      </button>
      <style>{`
        @media (prefers-reduced-motion: no-preference) {
          .pw-admin-toast {
            animation: pw-admin-toast-in 0.2s ease-out;
          }
        }
        @keyframes pw-admin-toast-in {
          0% { opacity: 0; transform: translateY(-8px); }
          100% { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

function AlertSettingsTab() {
  const [settings, setSettings] = useState<AlertSetting[] | null>(null);
  const [toast, setToast] = useState<{ id: number; message: React.ReactNode } | null>(null);
  const toastIdRef = useRef(0);
  const toastTimerRef = useRef<number | null>(null);

  function refresh() {
    listAlertSettings().then(setSettings);
  }
  useEffect(refresh, []);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    };
  }, []);

  function dismissToast() {
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    setToast(null);
  }

  function showToast(message: React.ReactNode) {
    toastIdRef.current += 1;
    setToast({ id: toastIdRef.current, message });
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2000);
  }

  async function handleUpdate(s: AlertSetting) {
    await updateAlertSetting(s.module, { urgency_threshold: s.urgency_threshold, enabled: s.enabled, recipients: s.recipients });
    refresh();
  }

  async function handleSendDigest() {
    if (!digestSetting?.enabled) {
      showToast(
        <>
          Enable <strong>Daily Digest</strong> to send reports.
        </>
      );
      return;
    }
    showToast("Sending daily digest…");
    try {
      const result = await sendDigestNow();
      showToast(
        result.sent
          ? `Sent to ${result.recipients?.length ?? 0} recipient(s), ${result.total_alerts ?? 0} open alert(s).`
          : `Not sent: ${result.reason}`
      );
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to send digest");
    }
  }

  if (!settings) return <Skeleton rows={4} height={32} />;
  const digestSetting = settings.find((s) => s.module === "daily_digest");

  return (
    <div>
      <Table>
        <THead>
          <Tr>
            <Th>Module</Th>
            <Th>Enabled</Th>
            <Th>Threshold</Th>
            <Th>Recipients</Th>
          </Tr>
        </THead>
        <TBody>
          {settings.map((s) => (
            <Tr key={s.module}>
              <Td>
                <span style={{ textTransform: "capitalize", fontWeight: 600 }}>{s.module.replace(/_/g, " ")}</span>
              </Td>
              <Td>
                <input
                  type="checkbox"
                  checked={s.enabled}
                  onChange={(e) => handleUpdate({ ...s, enabled: e.target.checked })}
                  style={{ accentColor: "var(--color-step-current)" }}
                />
              </Td>
              <Td>
                <Select
                  compact
                  value={s.urgency_threshold}
                  onChange={(e) => handleUpdate({ ...s, urgency_threshold: e.target.value as AlertSetting["urgency_threshold"] })}
                  options={URGENCY_OPTIONS}
                />
              </Td>
              <Td wrap>
                <input
                  className="input"
                  style={{ height: 32, fontSize: 13 }}
                  defaultValue={s.recipients.join(", ")}
                  placeholder="ops@plant.com, supervisor@plant.com"
                  onBlur={(e) => handleUpdate({ ...s, recipients: e.target.value.split(",").map((r) => r.trim()).filter(Boolean) })}
                />
              </Td>
            </Tr>
          ))}
        </TBody>
      </Table>

      {digestSetting && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn-primary" onClick={handleSendDigest}>
            Send Daily Digest Now
          </button>
        </div>
      )}
      <AdminToast toast={toast} onClose={dismissToast} />
    </div>
  );
}

// BRD §4.7-equivalent staleness read for the admin overview: past cadence is
// "stale", well past it (3x) is the more severe flag — same threshold logic
// FreshnessBadge uses elsewhere, applied here to the plain module list this
// endpoint returns (module / last_updated_at / expected_cadence_hours only).
const SEVERE_STALE_MULTIPLIER = 3;

function freshnessBadge(row: FreshnessRow) {
  if (!row.last_updated_at) {
    return <Badge variant="neutral">No data</Badge>;
  }
  const hours = (Date.now() - new Date(row.last_updated_at).getTime()) / (1000 * 60 * 60);
  if (hours > row.expected_cadence_hours * SEVERE_STALE_MULTIPLIER) {
    return <Badge variant="critical">Overdue</Badge>;
  }
  if (hours > row.expected_cadence_hours) {
    return <Badge variant="warning">Stale</Badge>;
  }
  return <Badge variant="ok">Fresh</Badge>;
}

function FreshnessTab() {
  const [rows, setRows] = useState<FreshnessRow[] | null>(null);
  useEffect(() => {
    getFreshnessOverview().then(setRows);
  }, []);

  if (!rows) return <Skeleton rows={4} height={32} />;
  if (rows.length === 0) {
    return <EmptyState title="Nothing to show yet" message="Freshness tracking starts once a module has its first data upload." />;
  }

  return (
    <Table>
      <THead>
        <Tr>
          <Th>Module</Th>
          <Th>Last updated</Th>
          <Th>Expected cadence</Th>
          <Th>Freshness</Th>
        </Tr>
      </THead>
      <TBody>
        {rows.map((r) => (
          <Tr key={r.module}>
            <Td>
              <span style={{ textTransform: "capitalize", fontWeight: 600 }}>{r.module.replace(/_/g, " ")}</span>
            </Td>
            <Td>
              <span className="num" style={{ color: "var(--color-text-secondary)" }}>
                {r.last_updated_at ? new Date(r.last_updated_at).toLocaleString() : "Never"}
              </span>
            </Td>
            <Td>
              <span className="num" style={{ color: "var(--color-text-secondary)" }}>every {r.expected_cadence_hours}h</span>
            </Td>
            <Td>{freshnessBadge(r)}</Td>
          </Tr>
        ))}
      </TBody>
    </Table>
  );
}

function AuditLogTab() {
  const [entries, setEntries] = useState<AuditLogEntry[] | null>(null);
  useEffect(() => {
    getAuditLog().then(setEntries);
  }, []);

  if (!entries) return <Skeleton rows={6} height={28} />;
  if (entries.length === 0) {
    return <EmptyState title="No activity yet" message="No configuration changes or uploads recorded yet." />;
  }

  return (
    <Table>
      <THead>
        <Tr>
          <Th>User</Th>
          <Th>Action</Th>
          <Th>Entity</Th>
          <Th>Details</Th>
          <Th>When</Th>
        </Tr>
      </THead>
      <TBody>
        {entries.map((e) => (
          <Tr key={e.id}>
            <Td>{e.user_email}</Td>
            <Td>
              <span style={{ fontWeight: 600 }}>{e.action}</span>
            </Td>
            <Td>
              <span style={{ color: "var(--color-text-secondary)" }}>
                {e.entity_type}
                {e.entity_id ? ` #${e.entity_id}` : ""}
              </span>
            </Td>
            <Td wrap>
              <span style={{ color: "var(--color-text-secondary)" }}>{e.details}</span>
            </Td>
            <Td>
              <span className="num" style={{ color: "var(--color-text-secondary)" }}>{new Date(e.created_at).toLocaleString()}</span>
            </Td>
          </Tr>
        ))}
      </TBody>
    </Table>
  );
}

type Tab = "users" | "alerts" | "freshness" | "audit" | "data_sources";

const TABS: Array<{ key: Tab; label: string }> = [
  { key: "users", label: "Users & Roles" },
  { key: "data_sources", label: "Data Sources" },
  { key: "alerts", label: "Alert Settings" },
  { key: "freshness", label: "Data Health" },
  { key: "audit", label: "Audit Log" },
];

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("users");

  return (
    <div>
      <PageHeader
        icon={<ModuleIcon name="admin" />}
        title="Admin Console"
        subtitle="Manage teammates and roles, tune alert routing, and keep an eye on system and data health."
      />

      <Tabs items={TABS} active={tab} onChange={(key) => setTab(key as Tab)} />

      {tab === "users" && <UsersTab />}
      {tab === "data_sources" && (
        <DataSourceSetup
          embedded={false}
          // Started with manual entry, or added another table later — this
          // is the same connect-once/map-everything flow onboarding uses,
          // just reachable any time afterward instead of only once.
        />
      )}
      {tab === "alerts" && <AlertSettingsTab />}
      {tab === "freshness" && <FreshnessTab />}
      {tab === "audit" && <AuditLogTab />}
    </div>
  );
}
