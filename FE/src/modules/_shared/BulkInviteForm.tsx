import React, { useState } from "react";

import { BulkInviteResult, inviteUsersBulk } from "../../api/admin";
import { Select } from "../../components/Select";

const ROLE_OPTIONS = ["operator", "viewer", "admin"] as const;

interface BulkInviteFormProps {
  roles?: readonly string[];
  onInvited?: (result: BulkInviteResult) => void;
}

/**
 * Paste a comma-separated list of emails and invite them all in one submit
 * — the multi-email alternative to the single-invite form once per
 * teammate (PRD §5.1 "invites its team", §6.1 "Admin invites team and
 * assigns roles"). Full names aren't required here; the backend derives a
 * display name from each email's local-part.
 */
export function BulkInviteForm({ roles = ROLE_OPTIONS, onInvited }: BulkInviteFormProps) {
  const [text, setText] = useState("");
  const [role, setRole] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<BulkInviteResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const emails = Array.from(
    new Set(
      text
        .split(/[\n,;]+/)
        .map((s) => s.trim())
        .filter(Boolean)
    )
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (emails.length === 0 || !role) return;
    setSaving(true);
    setError(null);
    setResult(null);
    try {
      const res = await inviteUsersBulk({ invites: emails.map((email) => ({ email })), default_role: role });
      setResult(res);
      onInvited?.(res);
      // Leave the failed addresses (and the role picked for them) in place
      // so they're easy to fix and resubmit instead of having to re-paste
      // the whole list and re-choose a role.
      if (res.errors.length === 0) {
        setText("");
        setRole("");
      } else {
        setText(res.errors.map((e) => e.email).join(", "));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to invite team");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: 6 }}>
        Enter email addresses separated by commas.
      </label>
      <input
        className="input"
        type="text"
        style={{ width: "100%" }}
        placeholder="name@company.com, name@company.com, .."
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, justifyContent: "flex-end" }}>
        <Select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          options={roles.map((r) => ({ value: r, label: r[0].toUpperCase() + r.slice(1) }))}
          placeholder="Select role"
          style={{ width: 160 }}
        />
        <button className="btn-primary" type="submit" disabled={saving || emails.length === 0 || !role}>
          {saving ? "Inviting…" : "Invite All"}
        </button>
      </div>
      {error && <div style={{ color: "var(--color-error-600)", fontSize: 13, marginTop: 8 }}>{error}</div>}
      {result && (
        <div style={{ fontSize: 13, marginTop: 8 }}>
          {result.invited.length > 0 && (
            <div style={{ color: "var(--color-success-700)" }}>Invited: {result.invited.map((u) => u.email).join(", ")}</div>
          )}
          {result.errors.length > 0 && (
            <div style={{ color: "var(--color-error-600)" }}>
              {result.errors.map((e) => `${e.email}: ${e.message}`).join("; ")}
            </div>
          )}
        </div>
      )}
    </form>
  );
}
