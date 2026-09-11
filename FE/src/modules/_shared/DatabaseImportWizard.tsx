import React, { useEffect, useState } from "react";

import {
  commitTableImport,
  createSyncSchedule,
  deleteSyncSchedule,
  listSchemas,
  listSyncSchedules,
  listTables,
  mapTableColumns,
  setSyncScheduleEnabled,
  testConnection,
  validateTable,
  type DbConnectionInput,
  type DiscoveredTable,
  type SyncSchedule,
} from "../../api/dbImport";
import type { CommitResult, MappingResult, ValidationResult } from "../../api/types";
import { Select } from "../../components/Select";
import { ConnectorManager } from "./ConnectorManager";
import { ImportReview } from "./ImportReview";
import { QuickField } from "./QuickLogForm";
import { markDatabaseConnected } from "./useSyncStatus";

type DbSource = "cloud" | "local";

interface DatabaseImportWizardProps {
  /** Matches a key in app/modules/db_import/service.py's entity registry — e.g. "assets". */
  entity: string;
  /** Human label, e.g. "Assets". */
  title: string;
  moduleLabel: string;
  description?: React.ReactNode;
  onCommitted?: () => void;
  embedded?: boolean;
}

type Step = "connect" | "browse" | "map" | "validate" | "commit";

const STEPS: Array<{ key: Step; label: string }> = [
  { key: "connect", label: "Connect" },
  { key: "browse", label: "Pick a table" },
  { key: "map", label: "Map fields" },
  { key: "validate", label: "Review & edit" },
  { key: "commit", label: "Confirm" },
];

const inputStyle: React.CSSProperties = { fontSize: 13 };

/**
 * Database Import — the "database" source for the same shared pipeline
 * CsvUploadFlow drives for files: only the extraction step (connect to a
 * customer's database, browse tables, read rows) is different here; field
 * mapping, validation, the editable preview grid, and commit are all the
 * exact same <ImportReview> the CSV flow uses.
 *
 * Backend contract (app/modules/db_import/router.py):
 *   POST /db-import/test-connection      -> detect engine (+ optionally save the connection, encrypted)
 *   POST /db-import/schemas              -> list schemas
 *   POST /db-import/{entity}/tables      -> list tables, ranked by intelligent-table-detection score
 *   POST /db-import/{entity}/map         -> MappingResult (same shape as CSV's /map)
 *   POST /db-import/{entity}/validate    -> ValidationResult (same shape as CSV's /validate)
 *   POST /db-import/{entity}/commit      -> CommitResult (same shape as CSV's /commit)
 */
export function DatabaseImportWizard({ entity, title, moduleLabel, description, onCommitted, embedded }: DatabaseImportWizardProps) {
  const [dbSource, setDbSource] = useState<DbSource>("cloud");
  const [form, setForm] = useState({ host: "", port: "", database: "", username: "", password: "", ssl: false });
  const [saveAsName, setSaveAsName] = useState("");

  const [testing, setTesting] = useState(false);
  const [connection, setConnection] = useState<DbConnectionInput | null>(null);
  const [detectedEngine, setDetectedEngine] = useState<string | null>(null);

  const [schemas, setSchemas] = useState<string[] | null>(null);
  const [selectedSchema, setSelectedSchema] = useState<string>("");
  const [tables, setTables] = useState<DiscoveredTable[] | null>(null);
  const [loadingTables, setLoadingTables] = useState(false);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);

  const [mapping, setMapping] = useState<MappingResult | null>(null);
  const [mappingChoices, setMappingChoices] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [editedRows, setEditedRows] = useState<Record<string, unknown>[]>([]);
  const [validating, setValidating] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [commitResult, setCommitResult] = useState<CommitResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [syncSchedules, setSyncSchedules] = useState<SyncSchedule[]>([]);
  const [watermarkColumn, setWatermarkColumn] = useState("");
  const [intervalMinutes, setIntervalMinutes] = useState(15);
  const [creatingSync, setCreatingSync] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  function refreshSyncSchedules() {
    listSyncSchedules()
      .then((all) => setSyncSchedules(all.filter((s) => s.entity === entity)))
      .catch(() => undefined); // sync status is supplementary — a fetch failure here shouldn't block the wizard
  }

  useEffect(() => {
    refreshSyncSchedules();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleEnableSync() {
    if (!connection?.connection_id || !selectedTable || !watermarkColumn) return;
    setCreatingSync(true);
    setSyncError(null);
    try {
      const mappingPayload = Object.fromEntries(Object.entries(mappingChoices).filter(([, header]) => header)) as Record<string, string>;
      await createSyncSchedule({
        entity,
        connection_id: connection.connection_id,
        schema_name: selectedSchema || null,
        table: selectedTable,
        column_mapping: mappingPayload,
        watermark_column: watermarkColumn,
        interval_minutes: intervalMinutes,
      });
      refreshSyncSchedules();
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "Could not enable continuous sync");
    } finally {
      setCreatingSync(false);
    }
  }

  const step: Step = commitResult !== null ? "commit" : result ? "validate" : mapping ? "map" : tables ? "browse" : "connect";
  const stepIndex = commitResult !== null ? STEPS.length : STEPS.findIndex((s) => s.key === step);

  async function handleTestConnection() {
    setTesting(true);
    setError(null);
    try {
      const input: DbConnectionInput = {
        host: form.host,
        port: Number(form.port),
        username: form.username,
        password: form.password,
        database: form.database || null,
        ssl: form.ssl,
        save_as: saveAsName || null,
      };
      const res = await testConnection(input);
      const engine = res.detected[0];
      const resolved: DbConnectionInput = { ...input, engine };
      // Only when save_as actually resulted in a saved connection — a plain
      // test-without-saving mustn't hide every other page's Database Import
      // tab, since nothing was actually connected.
      if (res.saved_connection_id) markDatabaseConnected();
      setConnection(resolved);
      setDetectedEngine(engine);
      const schemaRes = await listSchemas(resolved);
      setSchemas(schemaRes.schemas);
      if (schemaRes.schemas.length === 1) {
        await handleBrowseTables(resolved, schemaRes.schemas[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect");
    } finally {
      setTesting(false);
    }
  }

  async function handleBrowseTables(resolvedConnection: DbConnectionInput, schema: string) {
    setSelectedSchema(schema);
    setLoadingTables(true);
    setError(null);
    try {
      const list = await listTables(entity, resolvedConnection, schema || null);
      setTables(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not list tables");
    } finally {
      setLoadingTables(false);
    }
  }

  async function handleSelectTable(table: string) {
    if (!connection) return;
    setSelectedTable(table);
    setError(null);
    try {
      const mr = await mapTableColumns(entity, connection, selectedSchema || null, table);
      setMapping(mr);
      const choices: Record<string, string> = {};
      for (const m of mr.mapping) choices[m.app_field] = m.matched_column ?? "";
      setMappingChoices(choices);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read this table's columns");
    }
  }

  async function handleValidate() {
    if (!connection || !selectedTable) return;
    setValidating(true);
    setError(null);
    setCommitResult(null);
    try {
      const mappingPayload = Object.fromEntries(Object.entries(mappingChoices).filter(([, header]) => header));
      const data = await validateTable(entity, connection, selectedSchema || null, selectedTable, mappingPayload);
      setResult(data);
      setEditedRows(data.rows.map((r) => r.values));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Validation failed");
    } finally {
      setValidating(false);
    }
  }

  async function handleCommit() {
    setCommitting(true);
    setError(null);
    try {
      const data = await commitTableImport(entity, editedRows, true);
      setCommitResult(data);
      onCommitted?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Commit failed");
    } finally {
      setCommitting(false);
    }
  }

  function reset() {
    setConnection(null);
    setDetectedEngine(null);
    setSchemas(null);
    setSelectedSchema("");
    setTables(null);
    setSelectedTable(null);
    setMapping(null);
    setMappingChoices({});
    setResult(null);
    setEditedRows([]);
    setCommitResult(null);
    setError(null);
    // Without this, a watermark column picked for the previous table could
    // silently carry over to a new table that doesn't even have a column by
    // that name — the select would look unselected but the stale value
    // would still be submittable, breaking that schedule's sync permanently.
    setWatermarkColumn("");
    setSyncError(null);
  }

  return (
    <div className={embedded ? undefined : "surface"} style={{ padding: embedded ? 0 : 24, marginBottom: embedded ? 0 : 20 }}>
      {!embedded && <div style={{ fontSize: 15, fontFamily: "var(--font-family-display)", fontWeight: 700, marginBottom: description ? 4 : 20 }}>{title}: Database Import</div>}
      {description && (
        <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginBottom: 20, lineHeight: 1.6, fontFamily: "var(--font-family-sans)" }}>
          {description}
        </div>
      )}

      {/* Which database — a cloud/live database this backend can reach
          directly, or one on the customer's own network that needs a Local
          Connector relaying requests instead. Rendered as one bordered
          control split into two segments (.seg-toggle), not two separate
          buttons, since exactly one of the two is always true. */}
      <div className="seg-toggle" style={{ marginBottom: 24 }}>
        <button
          type="button"
          className={dbSource === "cloud" ? "seg-toggle__option seg-toggle__option--active" : "seg-toggle__option"}
          onClick={() => setDbSource("cloud")}
        >
          Cloud / Live Database
        </button>
        <button
          type="button"
          className={dbSource === "local" ? "seg-toggle__option seg-toggle__option--active" : "seg-toggle__option"}
          onClick={() => setDbSource("local")}
        >
          Local Database (on your network)
        </button>
      </div>

      {dbSource === "local" ? (
        <ConnectorManager />
      ) : (
        <>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 20 }}>
        {STEPS.map((s, i) => {
          const done = i < stepIndex;
          const active = i === stepIndex;
          return (
            <React.Fragment key={s.key}>
              {/* Same filled-pill shape as the Manual Entry/File Upload/
                  Database Import selector (.seg-btn--active) — a tinted
                  background + border, not just a thin outline — but in
                  neutral tones instead of gold. The number circle itself
                  stays --color-step-current (black light / gray dark). */}
              <div
                style={{
                  display: "flex", alignItems: "center", gap: 8, flex: "none",
                  padding: active ? "3px 12px 3px 3px" : 0,
                  borderRadius: "var(--radius-full)",
                  background: active ? "var(--color-neutral-100)" : "transparent",
                  border: active ? "1.5px solid var(--color-border-strong)" : "1.5px solid transparent",
                }}
              >
                <span
                  style={{
                    width: 24, height: 24, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 11, fontWeight: 800, flex: "none",
                    background: done ? "var(--color-success-600)" : active ? "var(--color-step-current)" : "var(--color-neutral-100)",
                    color: done ? "var(--color-fill-solid-fg)" : active ? "var(--color-step-current-fg)" : "var(--color-text-tertiary)",
                  }}
                >
                  {done ? "✓" : i + 1}
                </span>
                <span style={{ fontSize: 13, fontWeight: active ? 700 : 600, color: active ? "var(--color-text-primary)" : done ? "var(--color-text-secondary)" : "var(--color-text-tertiary)", whiteSpace: "nowrap" }}>
                  {s.label}
                </span>
              </div>
              {i < STEPS.length - 1 && <span style={{ flex: 1, height: 2, background: done ? "var(--color-success-300)" : "var(--color-border-default)", margin: "0 12px" }} />}
            </React.Fragment>
          );
        })}
      </div>

      {error && (
        <div style={{ background: "var(--color-error-50)", border: "1px solid var(--color-error-200)", borderRadius: "var(--radius-lg)", padding: "12px 16px", marginBottom: 18, fontSize: 13, color: "var(--color-error-800)", fontWeight: 600 }}>
          {error}
        </div>
      )}

      {!connection && (
        <div style={{ background: "var(--color-neutral-100)", border: "1px solid var(--color-border-default)", borderRadius: "var(--radius-xl)", padding: "20px 22px", marginBottom: 22 }}>
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
                <input
                  type="checkbox"
                  checked={form.ssl}
                  onChange={(e) => setForm({ ...form, ssl: e.target.checked })}
                  style={{ accentColor: "var(--color-step-current)" }}
                />
                Use SSL
              </span>
            </QuickField>
          </div>
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", margin: "10px 0 0" }}>
            Recommended for databases hosted on AWS, Azure, or GCP. Leave this off for a database on your local network.
          </p>

          <QuickField label="Save this connection (optional)" style={{ marginTop: 18 }}>
            <input className="input" style={inputStyle} placeholder="Production Postgres" value={saveAsName} onChange={(e) => setSaveAsName(e.target.value)} />
          </QuickField>
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", margin: "8px 0 0" }}>
            Saves an encrypted copy of these credentials for future imports — manageable afterward from Admin &gt; Data
            Sources. Leave this blank to use them once.
          </p>

          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
            <button className="btn-primary" onClick={handleTestConnection} disabled={testing}>
              {testing ? "Testing Connection…" : "Test Connection"}
            </button>
          </div>
        </div>
      )}

      {connection && !mapping && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, marginBottom: 14 }}>
            Connected as <strong>{detectedEngine}</strong>, importing into {moduleLabel} · {title}.{" "}
            <button className="btn-secondary" onClick={reset}>
              Change Connection
            </button>
          </div>

          {schemas && schemas.length > 1 && (
            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 12.5, fontWeight: 700, display: "block", marginBottom: 8 }}>Schema</label>
              <Select
                value={selectedSchema}
                onChange={(e) => connection && handleBrowseTables(connection, e.target.value)}
                options={[{ value: "", label: "All schemas" }, ...schemas.map((s) => ({ value: s, label: s }))]}
              />
            </div>
          )}

          {loadingTables && <div style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>Loading tables…</div>}

          {tables && (
            <div className="sheet">
              <div className="sheet-scroll" style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Table</th>
                      <th>Schema</th>
                      <th className="num">Rows (est.)</th>
                      <th>Match</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {tables.map((t) => (
                      <tr key={`${t.schema_name}.${t.name}`}>
                        <td>{t.name}</td>
                        <td>{t.schema_name ?? "-"}</td>
                        <td className="num">{t.row_count_estimate ?? "-"}</td>
                        <td>
                          {t.recommendation_score > 0 ? (
                            <span title={t.recommendation_reason ?? undefined} style={{ fontSize: 11.5, fontWeight: 700, color: "var(--color-success-700)" }}>
                              Recommended
                            </span>
                          ) : (
                            <span style={{ fontSize: 11.5, color: "var(--color-text-tertiary)" }}>-</span>
                          )}
                        </td>
                        <td>
                          <button className="btn-primary" onClick={() => handleSelectTable(t.name)}>
                            {selectedTable === t.name ? "Selected" : "Select"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      <ImportReview
        title={title}
        sourceNoun="table"
        mapping={mapping}
        mappingChoices={mappingChoices}
        onMappingChoiceChange={(field, header) => setMappingChoices((prev) => ({ ...prev, [field]: header }))}
        onContinueToValidate={handleValidate}
        validating={validating}
        result={result}
        editedRows={editedRows}
        onRowsChange={setEditedRows}
        committing={committing}
        commitResult={commitResult}
        onCommit={handleCommit}
      />

      {/* Continuous sync — only offered once this import used a *saved*
          connection (connection_id set), since a one-time connection's
          credentials aren't kept anywhere to reuse on the next tick. A
          customer who skips this keeps re-running this wizard by hand
          (or uses manual entry / CSV upload) exactly as before. */}
      {commitResult && connection?.connection_id && selectedTable && (
        <div style={{ background: "var(--color-neutral-100)", border: "1px solid var(--color-border-default)", borderRadius: "var(--radius-xl)", padding: "20px 22px", marginTop: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }}>Keep this up to date automatically</div>
          <p style={{ fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.6, margin: "0 0 16px" }}>
            Instead of running this import by hand, Plantwise can re-check this table on a schedule and bring in only
            new rows.
          </p>

          {syncError && (
            <div style={{ background: "var(--color-error-50)", border: "1px solid var(--color-error-200)", borderRadius: "var(--radius-lg)", padding: "10px 14px", marginBottom: 14, fontSize: 12.5, color: "var(--color-error-800)", fontWeight: 600 }}>
              {syncError}
            </div>
          )}

          {syncSchedules.filter((s) => s.table_name === selectedTable).length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {syncSchedules
                .filter((s) => s.table_name === selectedTable)
                .map((s) => (
                  <div key={s.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, background: "var(--color-surface-default)", border: "1px solid var(--color-border-subtle)", borderRadius: "var(--radius-lg)", padding: "10px 14px" }}>
                    <div style={{ fontSize: 12.5 }}>
                      <div style={{ fontWeight: 700 }}>Every {s.interval_minutes} min · watermark: {s.watermark_column}</div>
                      <div style={{ color: "var(--color-text-tertiary)", marginTop: 2 }}>
                        {s.last_synced_at ? `Last synced ${new Date(s.last_synced_at).toLocaleString()}` : "Not yet run"}
                        {s.last_status === "failed" && s.last_error ? ` · failing: ${s.last_error}` : ""}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 8, flex: "none" }}>
                      <button
                        className="btn-secondary"
                        onClick={async () => {
                          await setSyncScheduleEnabled(s.id, !s.enabled);
                          refreshSyncSchedules();
                        }}
                      >
                        {s.enabled ? "Pause" : "Resume"}
                      </button>
                      <button
                        className="btn-danger"
                        onClick={async () => {
                          await deleteSyncSchedule(s.id);
                          refreshSyncSchedules();
                        }}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
            </div>
          ) : (
            <div style={{ display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
              <QuickField label="Watermark column" style={{ minWidth: 200 }}>
                <Select
                  value={watermarkColumn}
                  onChange={(e) => setWatermarkColumn(e.target.value)}
                  placeholder="Choose a column"
                  options={(mapping?.headers ?? []).map((h) => ({ value: h, label: h }))}
                />
              </QuickField>
              <QuickField label="Check every (minutes)" style={{ minWidth: 140 }}>
                <input
                  className="input"
                  style={inputStyle}
                  type="number"
                  min={5}
                  value={intervalMinutes}
                  onChange={(e) => setIntervalMinutes(Math.max(5, Number(e.target.value) || 5))}
                />
              </QuickField>
              <button className="btn-primary" onClick={handleEnableSync} disabled={creatingSync || !watermarkColumn}>
                {creatingSync ? "Enabling…" : "Enable Continuous Sync"}
              </button>
            </div>
          )}
          <p style={{ fontSize: 11, color: "var(--color-text-tertiary)", margin: "12px 0 0" }}>
            Pick a column that only ever increases for new rows, such as an ID or a timestamp. Plantwise uses it to
            fetch just what changed since the last check.
          </p>
        </div>
      )}
        </>
      )}
    </div>
  );
}
