import React, { useEffect, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import {
  commitTableImport,
  createSyncSchedule,
  deleteSavedConnection,
  deleteSyncSchedule,
  listImportableEntities,
  listSavedConnections,
  listSchemas,
  listSyncSchedules,
  listTables,
  mapTableColumns,
  testConnection,
  validateTable,
  type DbConnectionInput,
  type DiscoveredTable,
  type ImportableEntity,
  type SavedConnection,
  type SyncSchedule,
} from "../../api/dbImport";
import type { RowError } from "../../api/types";
import { Skeleton } from "../../components/Loading";
import { Select } from "../../components/Select";
import { ConnectorManager } from "./ConnectorManager";
import { QuickField } from "./QuickLogForm";
import { markDatabaseConnected, markDatabaseDisconnected } from "./useSyncStatus";

type DbSource = "cloud" | "local";

const DEFAULT_INTERVAL_MINUTES = 5;
const inputStyle: React.CSSProperties = { fontSize: 13 };

/** Best-effort default watermark column so onboarding never has to ask "which
 * column should we use to detect new rows" per entity — an id column sorts
 * as reliably as a real timestamp for "what's new since last time" purposes,
 * and is the most common case. Falls back to any time/date-like column, then
 * to the first column. Can be redone later (delete + re-map) if it's wrong. */
/** Groups row-validation errors by cause (ignoring the specific value quoted
 * in each message, e.g. two different "unknown reference 'X'" rows count as
 * the same cause) and turns each backend message into a plain-English reason
 * — the generic "didn't match the expected format" summary this replaces
 * lumped every distinct cause (missing value, bad type, bad enum, missing
 * parent row) into one meaningless bucket. Keeps one real (non-redacted)
 * example message per group — the specific value is exactly what's needed to
 * self-diagnose (e.g. which station/line pair is actually mismatched),
 * so grouping must not hide it. */
function summarizeErrors(errors: RowError[]): { reason: string; example: string; count: number }[] {
  const counts = new Map<string, { count: number; example: string }>();
  for (const e of errors) {
    const key = e.message.replace(/'[^']*'/g, "'…'");
    const existing = counts.get(key);
    if (existing) existing.count += 1;
    else counts.set(key, { count: 1, example: e.message });
  }
  return [...counts.entries()]
    .map(([message, { count, example }]) => ({ reason: friendlyReason(message), example, count }))
    .sort((a, b) => b.count - a.count);
}

function friendlyReason(message: string): string {
  if (message === "required value missing") return "a required field was blank";
  if (message.startsWith("unknown reference")) {
    return "referenced a row that doesn't exist in Plantwise yet — map that entity first, then retry this one";
  }
  if (message.startsWith("could not parse")) return `a value ${message.slice("could not parse ".length)}`;
  if (message.includes("not one of")) return `a value ${message}`;
  return message;
}

function pickWatermarkColumn(headers: string[]): string {
  const idIdx = headers.findIndex((h) => h.toLowerCase() === "id");
  if (idIdx >= 0) return headers[idIdx];
  const dateIdx = headers.findIndex((h) => /time|date|created|updated/i.test(h));
  if (dateIdx >= 0) return headers[dateIdx];
  return headers[0];
}

interface DataSourceSetupProps {
  /** Called once the user is done mapping (or skipping) entities and wants
   * to move on — onboarding advances to the next step; Admin just re-fetches. */
  onDone?: () => void;
  /** Drop the outer card border/shadow when already nested (e.g. onboarding). */
  embedded?: boolean;
  /** Called every time an entity successfully starts syncing — lets a host
   * page (onboarding's step-chip checklist) refresh its own status live,
   * separately from onDone (which only fires when the user is finished here). */
  onEntityMapped?: () => void;
}

type EntityMapStep = "browse" | "map" | "validate" | "done";

/** One entity's inline "map this table" flow — collapsed into a small card
 * until the user opts in, so 9 entities don't render 9 full wizards at once. */
function EntityMappingCard({
  entity,
  connection,
  schemaName,
  schedule,
  skipped,
  onSkip,
  onMapped,
}: {
  entity: ImportableEntity;
  connection: DbConnectionInput;
  schemaName: string | null;
  schedule: SyncSchedule | undefined;
  skipped: boolean;
  onSkip: () => void;
  onMapped: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [step, setStep] = useState<EntityMapStep>("browse");
  const [tables, setTables] = useState<DiscoveredTable[] | null>(null);
  const [loadingTables, setLoadingTables] = useState(false);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [mappingChoices, setMappingChoices] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<{ valid: number; errors: number; breakdown: { reason: string; example: string; count: number }[] } | null>(null);
  const [committing, setCommitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Closes the mapping flow without applying anything — if this was a
  // "Change Table" on an already-synced entity, its existing schedule is
  // untouched (only confirmAndSync ever deletes/replaces it).
  function cancel() {
    setExpanded(false);
    setStep("browse");
    setSelectedTable(null);
    setError(null);
  }

  async function expand() {
    setExpanded(true);
    // Restart the flow from the top every time — needed once an
    // already-synced entity can be reopened too, since without this a
    // second "Change Table" click would resume at the stale "done" step
    // (no render branch for it) instead of the table browser.
    setStep("browse");
    setSelectedTable(null);
    if (tables) return;
    setLoadingTables(true);
    setError(null);
    try {
      setTables(await listTables(entity.key, connection, schemaName));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not list tables");
    } finally {
      setLoadingTables(false);
    }
  }

  async function selectTable(table: string) {
    setSelectedTable(table);
    setError(null);
    try {
      const mr = await mapTableColumns(entity.key, connection, schemaName, table);
      setHeaders(mr.headers);
      const choices: Record<string, string> = {};
      for (const m of mr.mapping) choices[m.app_field] = m.matched_column ?? "";
      setMappingChoices(choices);
      setStep("map");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read this table's columns");
    }
  }

  async function confirmMapping() {
    if (!selectedTable) return;
    setError(null);
    try {
      const mappingPayload = Object.fromEntries(Object.entries(mappingChoices).filter(([, header]) => header));
      const result = await validateTable(entity.key, connection, schemaName, selectedTable, mappingPayload);
      setSummary({ valid: result.valid_rows.length, errors: result.errors.length, breakdown: summarizeErrors(result.errors) });
      setStep("validate");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Validation failed");
    }
  }

  async function confirmAndSync() {
    if (!selectedTable || !connection.connection_id) return;
    setCommitting(true);
    setError(null);
    try {
      const mappingPayload = Object.fromEntries(
        Object.entries(mappingChoices).filter(([, header]) => header)
      ) as Record<string, string>;
      const result = await validateTable(entity.key, connection, schemaName, selectedTable, mappingPayload);
      await commitTableImport(entity.key, result.valid_rows, true);
      // Re-mapping an already-synced entity: the backend has no upsert for
      // sync schedules (createSyncSchedule always inserts a new row), so
      // the old one must be removed first — otherwise both would run
      // independently and write into the same entity twice.
      if (schedule) {
        await deleteSyncSchedule(schedule.id);
      }
      await createSyncSchedule({
        entity: entity.key,
        connection_id: connection.connection_id,
        schema_name: schemaName,
        table: selectedTable,
        column_mapping: mappingPayload,
        watermark_column: pickWatermarkColumn(headers),
        interval_minutes: DEFAULT_INTERVAL_MINUTES,
      });
      onMapped();
      // Collapse straight back to the summary line ("Synced from X · every
      // Y min", now reflecting the new table) instead of leaving the
      // mapping flow open on a "done" step nothing renders for.
      setExpanded(false);
      setSelectedTable(null);
      setStep("browse");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not enable sync for this table");
    } finally {
      setCommitting(false);
    }
  }

  const isSynced = !!schedule?.enabled;

  return (
    <div
      style={{
        background: "var(--color-surface-default)",
        border: "1px solid var(--color-border-default)",
        borderRadius: "var(--radius-lg)",
        padding: "14px 16px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13.5 }}>{entity.label}</div>
          <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 2 }}>
            {isSynced
              ? `Synced from ${schedule!.table_name} · every ${schedule!.interval_minutes} min`
              : skipped
                ? "Skipped. Add this manually on its module page instead."
                : "Not mapped yet"}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flex: "none" }}>
          {expanded ? (
            // Same Cancel button style as Predictive Maintenance's AssetForm
            // and Production's LineForm — plain btn-secondary, no icon. Sits
            // in the same right-end slot "Map this table"/"Change Table" was
            // in, rather than a separate row once the flow opens below.
            <button type="button" onClick={cancel} className="btn-secondary btn-compact">
              Cancel
            </button>
          ) : (
            <>
              {!isSynced && (
                <button className="btn-secondary btn-compact" onClick={onSkip}>
                  Skip
                </button>
              )}
              <button className="btn-primary btn-compact" onClick={expand}>
                {isSynced ? "Change Table" : "Map this table"}
              </button>
            </>
          )}
        </div>
      </div>

      {expanded && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--color-border-subtle)" }}>
          {error && (
            <div style={{ background: "var(--color-error-50)", border: "1px solid var(--color-error-200)", borderRadius: "var(--radius-md)", padding: "8px 12px", marginBottom: 12, fontSize: 12.5, color: "var(--color-error-800)" }}>
              {error}
            </div>
          )}

          {step === "browse" && (
            loadingTables ? (
              <div style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>Loading tables…</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {(tables ?? []).map((t) => (
                  <button
                    key={`${t.schema_name}.${t.name}`}
                    className="btn-secondary"
                    style={{ justifyContent: "space-between", display: "flex" }}
                    onClick={() => selectTable(t.name)}
                  >
                    <span>{t.name}</span>
                    {t.recommendation_score > 0 && <span style={{ fontSize: 11, color: "var(--color-success-700)", fontWeight: 700 }}>Recommended</span>}
                  </button>
                ))}
                {tables && tables.length === 0 && (
                  <div style={{ fontSize: 12.5, color: "var(--color-text-tertiary)" }}>No tables found in this database.</div>
                )}
              </div>
            )
          )}

          {step === "map" && (
            <div>
              <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginBottom: 10 }}>
                Match each field to a column in <strong>{selectedTable}</strong>:
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
                {Object.keys(mappingChoices).map((field) => (
                  <label key={field} style={{ display: "grid", gridTemplateColumns: "140px 1fr", alignItems: "center", gap: 10, fontSize: 12.5 }}>
                    <span style={{ fontWeight: 600 }}>{field}</span>
                    <Select
                      compact
                      placeholder="Not mapped"
                      value={mappingChoices[field] ?? ""}
                      onChange={(e) => setMappingChoices((prev) => ({ ...prev, [field]: e.target.value }))}
                      options={headers.map((h) => ({ value: h, label: h }))}
                    />
                  </label>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn-secondary btn-compact" onClick={() => { setStep("browse"); setSelectedTable(null); setError(null); }}>
                  Change table
                </button>
                <button className="btn-primary btn-compact" onClick={confirmMapping}>
                  Preview
                </button>
              </div>
            </div>
          )}

          {step === "validate" && summary && (
            <div>
              <div style={{ fontSize: 13, marginBottom: summary.breakdown.length > 0 ? 6 : 12 }}>
                <strong style={{ color: "var(--color-success-700)" }}>{summary.valid} rows</strong> ready to import
                {summary.errors > 0 && <span style={{ color: "var(--color-error-700)" }}> · {summary.errors} skipped</span>}
              </div>
              {summary.breakdown.length > 0 && (
                <ul style={{ margin: "0 0 12px", padding: "0 0 0 18px", fontSize: 12.5, color: "var(--color-text-secondary)" }}>
                  {summary.breakdown.map((b) => (
                    <li key={b.reason}>
                      {b.count} row{b.count > 1 ? "s" : ""}: {b.reason}
                      <div style={{ color: "var(--color-text-tertiary)", fontSize: 11.5 }}>e.g. {b.example}</div>
                    </li>
                  ))}
                </ul>
              )}
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn-secondary btn-compact" onClick={() => { setStep("map"); setSummary(null); setError(null); }}>
                  Back to mapping
                </button>
                <button className="btn-primary btn-compact" onClick={confirmAndSync} disabled={committing}>
                  {committing ? "Setting up sync…" : "Confirm & Start Syncing"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Consolidated "connect once, map everything" flow — the recommended path at
 * onboarding, also reusable later from Admin for a tenant who started with
 * manual entry and wants to turn sync on. Connect a single database, then
 * map (or skip) each of the entities db_import supports; a mapped entity
 * starts syncing immediately at a 5-minute interval — no per-entity prompts
 * for watermark column or schedule, so this stays fast across up to 9 tables.
 */
export function DataSourceSetup({ onDone, embedded, onEntityMapped }: DataSourceSetupProps) {
  const [dbSource, setDbSource] = useState<DbSource>("cloud");
  const [savedConnections, setSavedConnections] = useState<SavedConnection[]>([]);
  const [selectedSavedId, setSelectedSavedId] = useState<number | "new">("new");
  const [form, setForm] = useState({ host: "", port: "", database: "", username: "", password: "", ssl: false, name: "" });
  const [testing, setTesting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [connection, setConnection] = useState<DbConnectionInput | null>(null);
  const [detectedEngine, setDetectedEngine] = useState<string | null>(null);
  const [schemas, setSchemas] = useState<string[]>([]);
  const [selectedSchema, setSelectedSchema] = useState<string>("");
  // True only for the initial "does a connection already exist" check on
  // mount — without this, !connection is true for that instant (connection
  // starts null, and only gets set once the auto-reconnect below resolves),
  // so this panel would flash the "Connect your database" form even for a
  // tenant that connected during onboarding, before flipping to the real
  // "Connected as X" view a moment later.
  const [checkingExisting, setCheckingExisting] = useState(true);
  // Collapsed by default — the connected-tables list is the least-used part
  // of this panel once mapping is done, so it starts out of the way behind
  // an explicit toggle instead of always taking up space.
  const [tablesExpanded, setTablesExpanded] = useState(false);

  const [entities, setEntities] = useState<ImportableEntity[]>([]);
  const [syncSchedules, setSyncSchedules] = useState<SyncSchedule[]>([]);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());

  // Shared by handleConnect (new or re-selected saved connection) and the
  // mount-time auto-reconnect below, so "show the connected view" only has
  // one implementation.
  async function connectWith(input: DbConnectionInput, isNewConnection: boolean) {
    const res = await testConnection(input);
    const engine = res.detected[0];
    const resolved: DbConnectionInput = isNewConnection
      ? { ...input, engine, connection_id: res.saved_connection_id }
      : { connection_id: input.connection_id };
    if (!resolved.connection_id) {
      throw new Error("Could not save this connection. Please try again.");
    }
    // A saved connection now definitely exists (new or reused) — every
    // other page's Database Import tab should hide immediately, not wait
    // for its next independent fetch.
    markDatabaseConnected();
    if (isNewConnection) {
      // savedConnections was only ever fetched once on mount, so a
      // brand-new connection's id isn't in it yet — without this,
      // activeConnection below can't find it, and the "connected as
      // {name} · {engine} · {host}" details never render even though the
      // connection succeeded.
      await listSavedConnections().then(setSavedConnections).catch(() => undefined);
    }
    setConnection(resolved);
    setDetectedEngine(engine);
    const schemaRes = await listSchemas(resolved);
    setSchemas(schemaRes.schemas);
    setSelectedSchema(schemaRes.schemas.length >= 1 ? schemaRes.schemas[0] : "");
  }

  useEffect(() => {
    listSavedConnections()
      .then(async (conns) => {
        setSavedConnections(conns);
        if (conns.length === 0) return;
        // A connection already exists (e.g. made during onboarding, or on a
        // previous visit here) — show it as connected instead of presenting
        // a "connect your database" form as if none did. Whichever was used
        // most recently is the one most likely to still be the active one.
        const mostRecent = [...conns].sort((a, b) => {
          const aTime = new Date(a.last_used_at ?? a.created_at).getTime();
          const bTime = new Date(b.last_used_at ?? b.created_at).getTime();
          return bTime - aTime;
        })[0];
        setSelectedSavedId(mostRecent.id);
        try {
          await connectWith({ connection_id: mostRecent.id }, false);
        } catch {
          // Stored connection no longer works (credentials revoked, DB
          // moved) — fall back to the connect form instead of getting stuck
          // on a permanent loading state.
        }
      })
      .catch(() => undefined)
      .finally(() => setCheckingExisting(false));
    listImportableEntities().then(setEntities).catch(() => undefined);
    refreshSchedules();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function refreshSchedules() {
    listSyncSchedules().then(setSyncSchedules).catch(() => undefined);
  }

  async function handleConnect() {
    setTesting(true);
    setError(null);
    try {
      const input: DbConnectionInput =
        selectedSavedId !== "new"
          ? { connection_id: selectedSavedId }
          : {
              host: form.host,
              port: Number(form.port),
              username: form.username,
              password: form.password,
              database: form.database || null,
              ssl: form.ssl,
              // A fixed, professional fallback — not date-stamped, so it
              // doesn't read as a different, one-off name on every
              // connection made without an explicit name.
              save_as: form.name.trim() || "Primary Database",
            };
      await connectWith(input, selectedSavedId === "new");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect");
    } finally {
      setTesting(false);
    }
  }

  // The one place a connection can be ended — deleting it here (rather than
  // per-module) is what makes "go to Admin > Data Sources to update your DB
  // details" actually true. The FK from sync_schedules to this connection is
  // ON DELETE CASCADE, so every entity syncing from it stops automatically;
  // nothing else needs cleaning up on this side beyond local state.
  async function handleDisconnect() {
    if (!connection?.connection_id) return;
    const name = savedConnections.find((c) => c.id === connection.connection_id)?.name ?? "this database";
    if (!window.confirm(`Disconnect "${name}"? Any entities syncing from it will stop, and its saved credentials will be deleted. You can reconnect afterward.`)) {
      return;
    }
    setDisconnecting(true);
    setError(null);
    try {
      await deleteSavedConnection(connection.connection_id);
      const remaining = savedConnections.filter((c) => c.id !== connection.connection_id);
      setSavedConnections(remaining);
      // Only when that was the last one — other saved connections may still
      // exist, in which case the Database Import tab should stay hidden.
      if (remaining.length === 0) markDatabaseDisconnected();
      setConnection(null);
      setDetectedEngine(null);
      setSchemas([]);
      setSelectedSchema("");
      setSkipped(new Set());
      setSelectedSavedId("new");
      refreshSchedules();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect");
    } finally {
      setDisconnecting(false);
    }
  }

  if (checkingExisting) {
    return (
      <div className={embedded ? undefined : "surface"} style={{ padding: embedded ? 0 : 24 }}>
        <Skeleton rows={3} />
      </div>
    );
  }

  if (!connection) {
    return (
      <div className={embedded ? undefined : "surface"} style={{ padding: embedded ? 0 : 24 }}>
        <div style={{ fontSize: 15, fontFamily: "var(--font-family-display)", fontWeight: 700, marginBottom: 4 }}>Connect your database</div>
        <p style={{ fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.6, marginBottom: 20 }}>
          One connection covers everything below: sensor readings, maintenance history, quality inspections, inventory
          movements, and your config data. Once you map a table, it stays synced automatically.
        </p>

        {error && (
          <div style={{ background: "var(--color-error-50)", border: "1px solid var(--color-error-200)", borderRadius: "var(--radius-lg)", padding: "12px 16px", marginBottom: 18, fontSize: 13, color: "var(--color-error-800)", fontWeight: 600 }}>
            {error}
          </div>
        )}

        {/* Which database: one this backend can reach directly, or one on
            the customer's own network that needs a Local Connector relaying
            requests instead. */}
        <div className="seg-toggle" style={{ marginBottom: 20 }}>
          <button
            type="button"
            className={dbSource === "cloud" ? "seg-toggle__option seg-toggle__option--active" : "seg-toggle__option"}
            onClick={() => setDbSource("cloud")}
          >
            Cloud or Reachable Database
          </button>
          <button
            type="button"
            className={dbSource === "local" ? "seg-toggle__option seg-toggle__option--active" : "seg-toggle__option"}
            onClick={() => setDbSource("local")}
          >
            Local Database (Behind Your Firewall)
          </button>
        </div>

        {dbSource === "local" ? (
          <ConnectorManager />
        ) : (
        <div style={{ background: "var(--color-neutral-100)", border: "1px solid var(--color-border-default)", borderRadius: "var(--radius-xl)", padding: "20px 22px" }}>
          {savedConnections.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12.5, fontWeight: 700, display: "block", marginBottom: 8 }}>Connection</label>
              <Select
                value={selectedSavedId}
                onChange={(e) => setSelectedSavedId(e.target.value === "new" ? "new" : Number(e.target.value))}
                options={[
                  { value: "new", label: "New connection" },
                  ...savedConnections.map((c) => ({ value: c.id, label: `${c.name} (${c.engine}, ${c.host})` })),
                ]}
              />
            </div>
          )}

          {selectedSavedId === "new" && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16 }}>
              <QuickField label="Host or IP address">
                <input className="input" style={inputStyle} placeholder="db.yourcompany.com" value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} />
              </QuickField>
              <QuickField label="Port">
                <input className="input" style={inputStyle} placeholder="5432" value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })} />
              </QuickField>
              <QuickField label="Database (optional)">
                <input className="input" style={inputStyle} placeholder="plantwise_production" value={form.database} onChange={(e) => setForm({ ...form, database: e.target.value })} />
              </QuickField>
              <QuickField label="Username">
                <input className="input" style={inputStyle} placeholder="readonly_user" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
              </QuickField>
              <QuickField label="Password">
                <input className="input" style={inputStyle} type="password" placeholder="••••••••" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              </QuickField>
              <QuickField label="Encryption">
                <span className="input" style={{ ...inputStyle, display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="checkbox" checked={form.ssl} onChange={(e) => setForm({ ...form, ssl: e.target.checked })} style={{ accentColor: "var(--color-step-current)" }} />
                  Use SSL
                </span>
              </QuickField>
              <QuickField label="Connection name (optional)" style={{ gridColumn: "1 / -1" }}>
                <input className="input" style={inputStyle} placeholder="Plant Historian" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </QuickField>
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
            <button className="btn-primary" onClick={handleConnect} disabled={testing}>
              {testing ? "Connecting…" : "Connect"}
            </button>
          </div>
        </div>
        )}
      </div>
    );
  }

  const activeConnection = savedConnections.find((c) => c.id === connection.connection_id);
  // Both our own auto-generated fallback ("Primary Database") and the older
  // date-stamped one ("Database connection (7/14/2026)") this replaced mean
  // the same thing: nobody typed a real name for this connection — so
  // neither should be presented as if it were one.
  const hasCustomName = !!activeConnection && activeConnection.name !== "Primary Database" && !/^Database connection \(/.test(activeConnection.name);

  return (
    <div className={embedded ? undefined : "surface"} style={{ padding: embedded ? 0 : 24 }}>
      {/* Status text + the collapse toggle both pushed to the top-right of
          the header row — same placement as a recommendation card's status
          (top-right of its own header row via marginLeft: auto), not a
          subtitle stacked under the title. */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div style={{ fontSize: 15, fontFamily: "var(--font-family-display)", fontWeight: 700 }}>
          {hasCustomName ? `Connected as ${activeConnection!.name}` : "Connected DB"}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, flex: "none" }}>
          {activeConnection && (
            <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--color-text-tertiary)", whiteSpace: "nowrap" }}>
              Connected • {new Date(activeConnection.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
            </span>
          )}
          <button
            type="button"
            className="btn-chevron"
            onClick={() => setTablesExpanded((v) => !v)}
            aria-label={tablesExpanded ? "Collapse connected tables" : "Expand connected tables"}
            aria-expanded={tablesExpanded}
          >
            {tablesExpanded ? <ChevronUp size={18} strokeWidth={2} /> : <ChevronDown size={18} strokeWidth={2} />}
          </button>
        </div>
      </div>
      {detectedEngine && (
        <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 2 }}>
          {detectedEngine[0].toUpperCase() + detectedEngine.slice(1)}
        </div>
      )}
      {/* One row, vertically centered — the paragraph and Disconnect sit on
          the same line instead of one stacked above/below the other. */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, marginTop: 6 }}>
        <p style={{ fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.6, margin: 0 }}>
          Select the tables you want to map and skip the rest. You can remove the connection at any time and
          reconnect whenever needed.
        </p>
        {/* Same style as Admin's Deactivate button (Users & Roles table) —
            .btn-danger, not a one-off outline variant. */}
        <button className="btn-danger btn-compact" style={{ flex: "none" }} onClick={handleDisconnect} disabled={disconnecting}>
          {disconnecting ? "Disconnecting…" : "Disconnect"}
        </button>
      </div>

      {error && (
        <div style={{ background: "var(--color-error-50)", border: "1px solid var(--color-error-200)", borderRadius: "var(--radius-lg)", padding: "12px 16px", margin: "10px 0", fontSize: 13, color: "var(--color-error-800)", fontWeight: 600 }}>
          {error}
        </div>
      )}

      {tablesExpanded && (
        <>
          {schemas.length > 1 && (
            <div style={{ margin: "14px 0 18px", maxWidth: 260 }}>
              <label style={{ fontSize: 12.5, fontWeight: 700, display: "block", marginBottom: 8 }}>Schema</label>
              <Select
                value={selectedSchema}
                onChange={(e) => setSelectedSchema(e.target.value)}
                options={schemas.map((s) => ({ value: s, label: s }))}
              />
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 18 }}>
            {entities.map((entity) => (
              <EntityMappingCard
                key={entity.key}
                entity={entity}
                connection={connection}
                schemaName={selectedSchema || null}
                schedule={syncSchedules.find((s) => s.entity === entity.key && s.enabled)}
                skipped={skipped.has(entity.key)}
                onSkip={() => setSkipped((prev) => new Set(prev).add(entity.key))}
                onMapped={() => {
                  refreshSchedules();
                  onEntityMapped?.();
                }}
              />
            ))}
          </div>
        </>
      )}

      {onDone && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: tablesExpanded ? 20 : 18 }}>
          <button className="btn-primary" onClick={onDone}>
            Continue
          </button>
        </div>
      )}
    </div>
  );
}
