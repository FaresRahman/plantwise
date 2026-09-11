import React, { useState } from "react";

import { BASE_URL, getToken } from "../../api/client";
import type { CommitResult, MappingResult, ValidationResult } from "../../api/types";
import { ImportReview } from "./ImportReview";

const API_BASE = BASE_URL;

async function authedFetch(path: string, options: RequestInit = {}) {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  try {
    return await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    // fetch() throws a browser-internal error ("Failed to fetch", ...) when
    // no HTTP response is ever received (server down, CORS rejection,
    // offline) — not something a plant operator should see verbatim.
    throw new Error("Can't reach the server right now. Check your connection and try again.");
  }
}

interface CsvUploadFlowProps {
  /** Human label, e.g. "Sensor Readings". Used for the downloaded filename + shown in the file summary card. */
  title: string;
  /** Module label shown in the file summary card, e.g. "Predictive Maintenance". */
  moduleLabel: string;
  /** Short description of what this specific CSV covers — distinguishes this
   * upload from other CSV flows on the same page (e.g. readings vs.
   * maintenance history). Plain string is fine; pass JSX (e.g. a sentence
   * plus `<code className="field-chip">` column-name chips) for a richer look. */
  description?: React.ReactNode;
  /** Module-relative paths, e.g. "/predictive-maintenance/csv/readings/template". */
  templatePath: string;
  /** Header-detection + auto field-mapping suggestion — see
   * core/ingestion.py:map_csv_columns. Optional only for back-compat; every
   * current CSV flow wires this up. */
  mapPath?: string;
  validatePath: string;
  commitPath: string;
  /** Called after a successful commit — use it to refetch whatever list/chart depends on this data. */
  onCommitted?: () => void;
  /** Drop the outer card border/shadow/background when this is already
   * nested inside another card (e.g. an onboarding step) — avoids stacking
   * two bordered "surface" cards on top of each other. */
  embedded?: boolean;
  /** Suppress just the `title` heading (card padding/border stays) — for
   * callers already showing this title one level up (e.g. FormSection), so
   * it doesn't repeat a few pixels below. */
  hideHeading?: boolean;
  /** db_import entity key (e.g. "sensor_readings") this upload also feeds —
   * the "syncing automatically" banner this used to show here now lives one
   * level up, in ConfigImportTabs, so it covers Manual Entry too instead of
   * just File Upload. Kept as a prop for API back-compat even though this
   * component no longer reads it directly. */
  syncEntity?: string;
  /** Column-name reference (e.g. <FieldChips fields={[...]} />) shown in
   * place of "No file selected yet" until a file is chosen — a quick "what
   * columns does this expect" reminder right where the user's about to pick
   * a file, instead of a separate row above the whole source switcher. */
  fieldChips?: React.ReactNode;
}

type Step = "upload" | "map" | "validate" | "commit";

const STEPS: Array<{ key: Step; label: string }> = [
  { key: "upload", label: "Upload file" },
  { key: "map", label: "Map fields" },
  { key: "validate", label: "Review & edit" },
  { key: "commit", label: "Confirm" },
];

const ACCEPTED_EXTENSIONS = ".csv,.xlsx,.xls";

/**
 * Shared CSV/Excel bulk-upload UI — matches the wireframe's "CSV INGEST /
 * VALIDATION" screen (step indicator, file summary card, error banner,
 * editable preview grid). Accepts .csv and .xlsx/.xls — plant staff commonly
 * keep this data in spreadsheets, so both are first-class (see
 * core/ingestion.py:_read_table, which detects format by extension).
 *
 * Full flow (core/ingestion.py has the matching backend contract):
 *   GET  {templatePath}  -> text/csv file download (the template is always
 *                           CSV for simplicity; upload accepts either format)
 *   POST {mapPath}       -> multipart "file" -> MappingResult (detected
 *                           headers + suggested app-field mapping)
 *   POST {validatePath}  -> multipart "file" + "mapping" (JSON) -> ValidationResult, nothing committed
 *   POST {commitPath}    -> multipart "edited_rows" (JSON array of row values,
 *                           from the editable preview grid) + "skip_invalid"
 *                           -> CommitResult
 * All Dev A modules use this one component instead of hand-rolling their own
 * upload flow — keep it that way rather than forking a per-module copy.
 */
export function CsvUploadFlow({
  title,
  moduleLabel,
  description,
  templatePath,
  mapPath,
  validatePath,
  commitPath,
  onCommitted,
  embedded,
  hideHeading,
  fieldChips,
}: CsvUploadFlowProps) {
  const [file, setFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState<MappingResult | null>(null);
  const [mappingChoices, setMappingChoices] = useState<Record<string, string>>({});
  const [mappingLoading, setMappingLoading] = useState(false);
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [editedRows, setEditedRows] = useState<Record<string, unknown>[]>([]);
  const [validating, setValidating] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [commitResult, setCommitResult] = useState<CommitResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const step: Step = commitResult !== null ? "commit" : result ? "validate" : mapping ? "map" : "upload";
  const allDone = commitResult !== null;

  async function downloadTemplate() {
    const res = await authedFetch(templatePath);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title.toLowerCase().replace(/\s+/g, "-")}-template.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleFileSelected(f: File | null) {
    reset();
    setFile(f);
    if (!f) return;
    if (!mapPath) return; // back-compat: modules that haven't wired /map yet skip straight to validate
    setMappingLoading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", f);
      const res = await authedFetch(mapPath, { method: "POST", body: form });
      if (!res.ok) throw new Error(await res.text());
      const data: MappingResult = await res.json();
      setMapping(data);
      const choices: Record<string, string> = {};
      for (const m of data.mapping) choices[m.app_field] = m.matched_column ?? "";
      setMappingChoices(choices);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read this file's columns");
      setFile(null);
    } finally {
      setMappingLoading(false);
    }
  }

  async function handleValidate() {
    if (!file) return;
    setValidating(true);
    setError(null);
    setCommitResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      if (mapping) {
        const mappingPayload = Object.fromEntries(
          Object.entries(mappingChoices).filter(([, header]) => header)
        );
        form.append("mapping", JSON.stringify(mappingPayload));
      }
      const res = await authedFetch(validatePath, { method: "POST", body: form });
      if (!res.ok) throw new Error(await res.text());
      const data: ValidationResult = await res.json();
      setResult(data);
      setEditedRows(data.rows.map((r) => r.values));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Validation failed");
    } finally {
      setValidating(false);
    }
  }

  async function handleCommit() {
    if (!result) return;
    setCommitting(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("edited_rows", JSON.stringify(editedRows));
      // The user already had a chance to fix or knowingly leave invalid rows
      // in the editable grid — the backend revalidates edited_rows from
      // scratch regardless and reports exactly what it skipped and why.
      form.append("skip_invalid", "true");
      const res = await authedFetch(commitPath, { method: "POST", body: form });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        const message = body?.detail?.message ?? body?.detail ?? (await res.text().catch(() => "Commit failed"));
        throw new Error(typeof message === "string" ? message : "Commit failed");
      }
      const data: CommitResult = await res.json();
      setCommitResult(data);
      onCommitted?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Commit failed");
    } finally {
      setCommitting(false);
    }
  }

  function reset() {
    setFile(null);
    setMapping(null);
    setMappingChoices({});
    setResult(null);
    setEditedRows([]);
    setCommitResult(null);
    setError(null);
  }

  const stepIndex = allDone ? STEPS.length : STEPS.findIndex((s) => s.key === step);
  const invalidCount = result ? result.rows.filter((r) => !r.valid).length : 0;
  const warningCount = result ? result.rows.filter((r) => r.warnings.length > 0).length : 0;

  return (
    <div className={embedded ? undefined : "surface"} style={{ padding: embedded ? 0 : 24, marginBottom: embedded ? 0 : 20 }}>
      {/* embedded (onboarding) usage already has a sectionLabelStyle heading
          right above this component, so only the column-list description
          repeats here, not the title. Same for hideHeading (e.g. a
          FormSection title one level up already names this section). */}
      {!embedded && !hideHeading && (
        <div style={{ fontSize: 15, fontFamily: "var(--font-family-display)", fontWeight: 700, marginBottom: description ? 4 : 20 }}>{title}</div>
      )}
      {description && (
        <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginBottom: 20, lineHeight: 1.6, fontFamily: "var(--font-family-sans)" }}>
          {description}
        </div>
      )}

      {/* step indicator — connected progress dots, not a plain arrow chain */}
      <div style={{ display: "flex", alignItems: "center", marginBottom: 28 }}>
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
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  flex: "none",
                  padding: active ? "3px 12px 3px 3px" : 0,
                  borderRadius: "var(--radius-full)",
                  background: active ? "var(--color-neutral-100)" : "transparent",
                  border: active ? "1.5px solid var(--color-border-strong)" : "1.5px solid transparent",
                }}
              >
                <span
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: "50%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 11,
                    fontWeight: 800,
                    flex: "none",
                    background: done ? "var(--color-success-600)" : active ? "var(--color-step-current)" : "var(--color-neutral-100)",
                    color: done ? "var(--color-fill-solid-fg)" : active ? "var(--color-step-current-fg)" : "var(--color-text-tertiary)",
                  }}
                >
                  {done ? "✓" : i + 1}
                </span>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: active ? 700 : 600,
                    color: active ? "var(--color-text-primary)" : done ? "var(--color-text-secondary)" : "var(--color-text-tertiary)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {s.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <span style={{ flex: 1, height: 2, background: done ? "var(--color-success-300)" : "var(--color-border-default)", margin: "0 12px" }} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* file picker / summary card — one shade deeper than either the
          standalone page's white card or the onboarding wizard's tinted
          card, so it reads as a distinct zone against both. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          background: "var(--color-neutral-100)",
          border: embedded ? "none" : "1px solid var(--color-border-default)",
          borderRadius: "var(--radius-xl)",
          padding: "18px 20px",
          marginBottom: 20,
        }}
      >
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            background: "var(--color-neutral-100)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 800,
            color: "var(--color-neutral-500)",
            fontSize: 13,
            flex: "none",
          }}
        >
          {file ? file.name.split(".").pop()?.toUpperCase() : "FILE"}
        </div>
        {file ? (
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 14 }}>{file.name}</div>
            <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
              {moduleLabel} · {title}
              {result ? ` · ${result.total_rows} rows parsed` : mapping ? ` · ${mapping.headers.length} columns detected` : ""}
            </div>
          </div>
        ) : fieldChips ? (
          <div style={{ flex: 1, fontSize: 13, color: "var(--color-text-tertiary)", lineHeight: 1.8 }}>{fieldChips}</div>
        ) : (
          <div style={{ flex: 1, fontSize: 14, color: "var(--color-text-tertiary)" }}>No file selected yet</div>
        )}

        {result && (
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-success-700)" }}>{result.valid_rows.length} valid</div>
            {invalidCount > 0 && (
              <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-error-700)" }}>{invalidCount} errors</div>
            )}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, flex: "none" }}>
          <button className="btn-secondary" onClick={downloadTemplate}>
            Download template
          </button>
          <label className="btn-secondary">
            {file ? "Change file" : "Choose file"}
            <input
              type="file"
              accept={ACCEPTED_EXTENSIONS}
              style={{ display: "none" }}
              onChange={(e) => handleFileSelected(e.target.files?.[0] ?? null)}
            />
          </label>
          {file && mapPath && !mapping && !mappingLoading && (
            <button className="btn-primary" disabled>
              Reading file…
            </button>
          )}
          {file && (mapping || !mapPath) && !result && (
            <button className="btn-primary" onClick={handleValidate} disabled={validating}>
              {validating ? "Validating…" : "Validate"}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div
          style={{
            background: "var(--color-error-50)",
            border: "1px solid var(--color-error-200)",
            borderRadius: "var(--radius-lg)",
            padding: "12px 16px",
            marginBottom: 18,
            fontSize: 13,
            color: "var(--color-error-800)",
            fontWeight: 600,
          }}
        >
          {error}
        </div>
      )}

      <ImportReview
        title={title}
        sourceNoun="file"
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
    </div>
  );
}
