import React, { useEffect, useState } from "react";
import { Check, Copy, Download, KeyRound } from "lucide-react";

import { createConnector, downloadConnectorInstaller, listConnectors, revokeConnector, type Connector } from "../../api/dbImport";
import { Badge, type BadgeVariant } from "../../components/Badge";

/** There's only a packaged Windows build right now (PyInstaller doesn't
 * cross-compile — a real Mac/Linux build has to happen on that OS, not this
 * one). Detect the visitor's platform so we never offer a download that
 * doesn't exist; Mac/Linux instead get the "run from source" steps. */
function detectPlatform(): "windows" | "mac" | "other" {
  const ua = navigator.userAgent;
  if (/Win/i.test(ua)) return "windows";
  if (/Mac/i.test(ua)) return "mac";
  return "other";
}

const STATUS_VARIANT: Record<Connector["status"], BadgeVariant> = {
  active: "ok",
  pending: "warning",
  revoked: "neutral",
};
const STATUS_LABEL: Record<Connector["status"], string> = {
  active: "Active",
  pending: "Pending",
  revoked: "Revoked",
};

/**
 * Local DB Import — registering and managing Local Connectors for a
 * database this dashboard can't reach directly (on the customer's own
 * network, behind their firewall). The connector application, installed
 * next to that database, polls outbound for work and executes it locally —
 * their database credentials never reach this backend at all (see
 * BE/app/modules/db_import/connector_service.py).
 *
 * Browsing tables and importing data *through* an active connector, from
 * this dashboard, is still a separate follow-up (the backend job-relay API
 * it needs already exists — see BE/connector/README.md) — this screen
 * covers installing, registering, and managing connectors for now.
 */
export function ConnectorManager() {
  const [connectors, setConnectors] = useState<Connector[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [justCreated, setJustCreated] = useState<{ name: string; registration_key: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [showSourceSteps, setShowSourceSteps] = useState(false);
  const [platform] = useState(detectPlatform);

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    try {
      await downloadConnectorInstaller();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not download the connector installer");
    } finally {
      setDownloading(false);
    }
  }

  async function refresh() {
    try {
      setConnectors(await listConnectors());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load connectors");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const res = await createConnector(newName.trim());
      setJustCreated({ name: res.name, registration_key: res.registration_key });
      setCopied(false);
      setNewName("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not register connector");
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(c: Connector) {
    if (!window.confirm(`Revoke "${c.name}"? This can't be undone: it will need to be registered again to reconnect.`)) return;
    setError(null);
    try {
      await revokeConnector(c.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not revoke connector");
    }
  }

  function copyKey() {
    if (!justCreated) return;
    navigator.clipboard.writeText(justCreated.registration_key).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6, margin: "0 0 20px" }}>
        Use this if we can't connect to your database over the internet (for example, one kept behind your
        company's firewall). You'll install a small application next to that database; it contacts us on its own,
        so you don't need to open anything on your firewall, and your database password never leaves your network.
      </p>

      <div style={{ background: "var(--color-surface-default)", border: "1px solid var(--color-border-default)", borderRadius: "var(--radius-lg)", padding: "16px 20px", marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>How to install and connect it</div>
          {platform === "windows" ? (
            <button type="button" className="btn-secondary btn-compact" style={{ display: "inline-flex", alignItems: "center", gap: 6, flex: "none" }} onClick={handleDownload} disabled={downloading}>
              <Download size={13} strokeWidth={2} />
              {downloading ? "Downloading…" : "Download for Windows"}
            </button>
          ) : (
            <button type="button" className="btn-secondary btn-compact" style={{ flex: "none" }} onClick={() => setShowSourceSteps((s) => !s)}>
              {platform === "mac" ? "Set up on Mac" : "Set up on Linux"}
            </button>
          )}
        </div>
        <ol style={{ margin: 0, padding: "0 0 0 20px", display: "flex", flexDirection: "column", gap: 8 }}>
          <li style={{ fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
            Register a connector below to get a one time key.
          </li>
          <li style={{ fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
            {platform === "windows"
              ? "Download the Plantwise Local Connector above, and run it on a computer that is on the same network as your database."
              : "Set up the Plantwise Local Connector (see below) on a computer that is on the same network as your database."}
          </li>
          <li style={{ fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
            It opens a small setup page in your browser. Paste the key there to link it to your plant.
          </li>
          <li style={{ fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
            On that same setup page, enter your database's connection details. They stay on that computer and are
            never sent to us.
          </li>
          <li style={{ fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
            Come back to this page. The connector will switch to <strong>Active</strong> as soon as it finishes connecting.
          </li>
        </ol>

        {platform !== "windows" && showSourceSteps && (
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--color-border-subtle)" }}>
            <p style={{ fontSize: 12, color: "var(--color-text-tertiary)", margin: "0 0 8px" }}>
              A ready to run app for {platform === "mac" ? "Mac" : "Linux"} isn't available yet. Until then, whoever
              manages the database can run it from Python with these commands, on a computer that is on the same
              network as the database:
            </p>
            <pre
              className="num"
              style={{
                fontSize: 11.5, lineHeight: 1.7, background: "var(--color-neutral-50)", border: "1px solid var(--color-border-default)",
                borderRadius: "var(--radius-md)", padding: "10px 14px", margin: 0, overflowX: "auto",
              }}
            >
{`git clone <the Plantwise connector repository>
cd connector
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py`}
            </pre>
          </div>
        )}
      </div>

      {error && (
        <div style={{ background: "var(--color-error-50)", border: "1px solid var(--color-error-200)", borderRadius: "var(--radius-lg)", padding: "12px 16px", marginBottom: 18, fontSize: 13, color: "var(--color-error-800)", fontWeight: 600 }}>
          {error}
        </div>
      )}

      {justCreated && (
        <div style={{ background: "var(--color-accent-50)", border: "1px solid var(--color-accent-300)", borderRadius: "var(--radius-xl)", padding: "18px 20px", marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 700, marginBottom: 10, color: "var(--color-accent-900)" }}>
            <KeyRound size={15} strokeWidth={2} />
            Registration key for "{justCreated.name}": save it now, it won't be shown again
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <code
              className="num"
              style={{
                flex: 1,
                background: "var(--color-surface-default)",
                border: "1px solid var(--color-border-default)",
                borderRadius: "var(--radius-md)",
                padding: "8px 12px",
                fontSize: 13,
                wordBreak: "break-all",
              }}
            >
              {justCreated.registration_key}
            </code>
            <button type="button" className="btn-secondary" style={{ flex: "none", display: "inline-flex", alignItems: "center", gap: 5 }} onClick={copyKey}>
              {copied ? <Check size={13} strokeWidth={2.5} /> : <Copy size={13} strokeWidth={2} />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p style={{ fontSize: 11, color: "var(--color-accent-800)", margin: "12px 0 0" }}>
            Give this key to whoever sets up the Local Connector on the database's network. They enter it once
            during install to link it here. This connector shows as "Active" as soon as that's done.
          </p>
        </div>
      )}

      <form onSubmit={handleCreate} style={{ display: "flex", gap: 10, marginBottom: 24 }}>
        <input
          className="input"
          style={{ flex: 1 }}
          placeholder="Plant Floor Database"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button className="btn-primary" type="submit" disabled={creating || !newName.trim()}>
          {creating ? "Registering…" : "+ Register Connector"}
        </button>
      </form>

      {connectors === null ? (
        <div style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>Loading connectors…</div>
      ) : connectors.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>No connectors registered yet.</div>
      ) : (
        <div className="sheet">
          <div className="sheet-scroll" style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Registered</th>
                  <th>Last seen</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {connectors.map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}</td>
                    <td>
                      <Badge variant={STATUS_VARIANT[c.status]}>{STATUS_LABEL[c.status]}</Badge>
                    </td>
                    <td>
                      <span className="num" style={{ color: "var(--color-text-secondary)" }}>
                        {c.registered_at ? new Date(c.registered_at).toLocaleString() : ""}
                      </span>
                    </td>
                    <td>
                      <span className="num" style={{ color: "var(--color-text-secondary)" }}>
                        {c.last_seen_at ? new Date(c.last_seen_at).toLocaleString() : "Never"}
                      </span>
                    </td>
                    <td>
                      {c.status !== "revoked" && (
                        <button type="button" className="btn-secondary" onClick={() => handleRevoke(c)}>
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {connectors && connectors.some((c) => c.status === "active") && (
        <p style={{ fontSize: 12.5, color: "var(--color-text-tertiary)", marginTop: 18 }}>
          Browsing tables and importing through an active connector is coming soon. This screen covers registering
          and managing connectors for now.
        </p>
      )}
    </div>
  );
}
