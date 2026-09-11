import React from "react";

import type { CommitResult, MappingResult, ValidationResult } from "../../api/types";
import { EditablePreviewGrid } from "./EditablePreviewGrid";

const CONFIDENCE_LABEL: Record<string, string> = {
  exact: "Exact match",
  case_insensitive: "Matched",
  alias: "Matched",
  fuzzy: "Best guess",
  none: "Not detected",
};

const CONFIDENCE_COLOR: Record<string, string> = {
  exact: "var(--color-success-700)",
  case_insensitive: "var(--color-success-700)",
  alias: "var(--color-success-700)",
  fuzzy: "var(--color-warning-700)",
  none: "var(--color-error-700)",
};

interface ImportReviewProps {
  /** Used in "review how your {sourceNoun}'s columns map to {title} fields". */
  title: string;
  /** "file" for CsvUploadFlow, "table" for DatabaseImportWizard. */
  sourceNoun?: string;
  mapping: MappingResult | null;
  mappingChoices: Record<string, string>;
  onMappingChoiceChange: (field: string, header: string) => void;
  onContinueToValidate: () => void;
  validating: boolean;
  result: ValidationResult | null;
  editedRows: Record<string, unknown>[];
  onRowsChange: (rows: Record<string, unknown>[]) => void;
  committing: boolean;
  commitResult: CommitResult | null;
  onCommit: () => void;
}

/**
 * The source-agnostic back half of every import flow: field-mapping review,
 * the editable preview grid, and the confirm/commit action + result. Both
 * CsvUploadFlow (source = uploaded file) and DatabaseImportWizard (source =
 * a live database table) render this — only how rows get *extracted*
 * differs between them; everything from "here's the detected mapping"
 * onward is identical.
 */
export function ImportReview({
  title,
  sourceNoun = "file",
  mapping,
  mappingChoices,
  onMappingChoiceChange,
  onContinueToValidate,
  validating,
  result,
  editedRows,
  onRowsChange,
  committing,
  commitResult,
  onCommit,
}: ImportReviewProps) {
  const invalidCount = result ? result.rows.filter((r) => !r.valid).length : 0;
  const warningCount = result ? result.rows.filter((r) => r.warnings.length > 0).length : 0;

  return (
    <>
      {/* field-mapping review — shown once headers are detected, before
          validation actually runs against them */}
      {mapping && !result && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>
            Field mapping: review how your {sourceNoun}'s columns map to {title.toLowerCase()} fields, and adjust any that look wrong.
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr auto",
              gap: "8px 12px",
              alignItems: "center",
              background: "var(--color-neutral-100)",
              border: "1px solid var(--color-border-default)",
              borderRadius: "var(--radius-xl)",
              padding: "14px 16px",
            }}
          >
            {mapping.mapping.map((m) => (
              <React.Fragment key={m.app_field}>
                <div style={{ fontSize: 13, fontWeight: 700 }}>
                  {m.app_field}
                  {m.required && <span style={{ color: "var(--color-error-500)" }}> *</span>}
                </div>
                <select
                  value={mappingChoices[m.app_field] ?? ""}
                  onChange={(e) => onMappingChoiceChange(m.app_field, e.target.value)}
                  style={{
                    fontSize: 13,
                    padding: "6px 8px",
                    borderRadius: "var(--radius-md)",
                    border: "1px solid var(--color-border-default)",
                    background: "var(--color-background-primary, transparent)",
                    color: "var(--color-text-primary)",
                  }}
                >
                  <option value="">Not mapped</option>
                  {mapping.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
                <span style={{ fontSize: 11.5, fontWeight: 700, color: CONFIDENCE_COLOR[m.confidence], whiteSpace: "nowrap" }}>
                  {CONFIDENCE_LABEL[m.confidence]}
                </span>
              </React.Fragment>
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
            <button className="btn-primary" onClick={onContinueToValidate} disabled={validating}>
              {validating ? "Validating…" : "Continue to validation"}
            </button>
          </div>
        </div>
      )}

      {result && (invalidCount > 0 || warningCount > 0) && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            background: invalidCount > 0 ? "var(--color-error-50)" : "var(--color-warning-50)",
            border: `1px solid ${invalidCount > 0 ? "var(--color-error-200)" : "var(--color-warning-200)"}`,
            borderRadius: "var(--radius-lg)",
            padding: "12px 16px",
            marginBottom: 14,
          }}
        >
          <span
            style={{
              fontSize: 13,
              color: invalidCount > 0 ? "var(--color-error-800)" : "var(--color-warning-800)",
              fontWeight: 600,
              flex: 1,
            }}
          >
            {invalidCount > 0 && `${invalidCount} row(s) have errors: fix them below or they'll be skipped on import. `}
            {warningCount > 0 && `${warningCount} row(s) already exist and will be updated. `}
            Edit any cell directly, or add/remove rows, before confirming.
          </span>
        </div>
      )}

      {result && <EditablePreviewGrid columns={result.columns} rows={result.rows} onRowsChange={onRowsChange} />}

      {result && (
        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 12 }}>
          {commitResult === null ? (
            <button className="btn-primary" onClick={onCommit} disabled={committing || editedRows.length === 0}>
              {committing ? "Confirming…" : `Confirm import (${editedRows.length} row(s))`}
            </button>
          ) : (
            <span style={{ color: "var(--color-success-700)", fontSize: 13, fontWeight: 700 }}>
              Committed {commitResult.committed} row(s).
              {commitResult.updated ? ` ${commitResult.updated} updated.` : ""}
              {commitResult.skipped > 0 ? ` ${commitResult.skipped} invalid row(s) were skipped.` : ""}
              {commitResult.processing_time_ms != null ? ` (${Math.round(commitResult.processing_time_ms)}ms)` : ""}
            </span>
          )}
        </div>
      )}
    </>
  );
}
