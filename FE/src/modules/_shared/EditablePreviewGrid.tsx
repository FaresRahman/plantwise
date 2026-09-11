import React, { useEffect, useMemo, useRef, useState } from "react";

import type { ColumnMeta, RowPreview } from "../../api/types";

interface EditableRow extends RowPreview {
  id: string;
}

type StatusFilter = "all" | "errors" | "warnings" | "valid";
type SortState = { column: string; direction: "asc" | "desc" } | null;

let nextRowId = 0;
function makeId() {
  nextRowId += 1;
  return `row-${nextRowId}`;
}

function toEditableRows(rows: RowPreview[]): EditableRow[] {
  return rows.map((r) => ({ ...r, id: makeId() }));
}

function blankValues(columns: ColumnMeta[]): Record<string, unknown> {
  return Object.fromEntries(columns.map((c) => [c.name, ""]));
}

function cellIssues(row: EditableRow, columnName: string) {
  return {
    error: row.errors.find((e) => e.column === columnName)?.message,
    warning: row.warnings.find((w) => w.column === columnName)?.message,
  };
}

function rowLevelIssues(row: EditableRow) {
  return {
    errors: row.errors.filter((e) => !e.column).map((e) => e.message),
    warnings: row.warnings.filter((w) => !w.column).map((w) => w.message),
  };
}

function compareValues(a: unknown, b: unknown): number {
  const an = a === null || a === undefined || a === "" ? null : Number(a);
  const bn = b === null || b === undefined || b === "" ? null : Number(b);
  if (an !== null && bn !== null && !Number.isNaN(an) && !Number.isNaN(bn)) return an - bn;
  const as = a === null || a === undefined ? "" : String(a);
  const bs = b === null || b === undefined ? "" : String(b);
  return as.localeCompare(bs);
}

interface EditablePreviewGridProps {
  columns: ColumnMeta[];
  rows: RowPreview[];
  /** Fires whenever the row set changes (edit/add/delete) with the current
   * edited values, keyed by app field name — this is exactly the payload
   * `CsvUploadFlow` posts to the commit endpoint as `edited_rows`. */
  onRowsChange: (rows: Record<string, unknown>[]) => void;
}

/**
 * Editable spreadsheet-style grid shown after CSV/Excel validation — every
 * uploaded row (valid or not), with typed inputs per column, invalid cells
 * outlined red with a tooltip, warning rows tinted amber, and row add/delete.
 * "Confirm import" (owned by CsvUploadFlow) posts the current edited values
 * straight to the commit endpoint, which revalidates from scratch server-side
 * — this component never re-validates locally, it just tracks edits.
 */
export function EditablePreviewGrid({ columns, rows, onRowsChange }: EditablePreviewGridProps) {
  const [editableRows, setEditableRows] = useState<EditableRow[]>(() => toEditableRows(rows));
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<SortState>(null);
  const firstRun = useRef(true);

  // A brand-new validation result (new file, or re-validated after a mapping
  // change) means the previous edit session no longer applies — reset.
  useEffect(() => {
    setEditableRows(toEditableRows(rows));
    firstRun.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);

  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
    onRowsChange(editableRows.map((r) => r.values));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editableRows]);

  function updateCell(id: string, columnName: string, value: string) {
    setEditableRows((prev) =>
      prev.map((r) => {
        if (r.id !== id) return r;
        const errors = r.errors.filter((e) => e.column !== columnName);
        const warnings = r.warnings.filter((w) => w.column !== columnName);
        return {
          ...r,
          values: { ...r.values, [columnName]: value },
          errors,
          warnings,
          valid: errors.length === 0,
        };
      })
    );
  }

  function deleteRow(id: string) {
    setEditableRows((prev) => prev.filter((r) => r.id !== id));
  }

  function addRow() {
    setEditableRows((prev) => [
      ...prev,
      { id: makeId(), row: -1, values: blankValues(columns), valid: true, errors: [], warnings: [] },
    ]);
  }

  function toggleSort(column: string) {
    setSort((prev) => {
      if (!prev || prev.column !== column) return { column, direction: "asc" };
      if (prev.direction === "asc") return { column, direction: "desc" };
      return null;
    });
  }

  // Search/filter/sort only ever change what's *displayed* — edits, add,
  // and delete always act on `editableRows` (by row.id), the full set, so
  // onRowsChange keeps emitting every row regardless of the current view.
  const visibleRows = useMemo(() => {
    let list = editableRows;
    if (statusFilter === "errors") list = list.filter((r) => !r.valid);
    else if (statusFilter === "warnings") list = list.filter((r) => r.warnings.length > 0);
    else if (statusFilter === "valid") list = list.filter((r) => r.valid && r.warnings.length === 0);

    const term = search.trim().toLowerCase();
    if (term) {
      list = list.filter((r) => Object.values(r.values).some((v) => v !== null && v !== undefined && String(v).toLowerCase().includes(term)));
    }

    if (sort) {
      const { column, direction } = sort;
      list = [...list].sort((a, b) => {
        const cmp = compareValues(a.values[column], b.values[column]);
        return direction === "asc" ? cmp : -cmp;
      });
    }
    return list;
  }, [editableRows, search, statusFilter, sort]);

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <input
          className="input"
          type="text"
          placeholder="Search rows…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ maxWidth: 220, fontSize: 12.5 }}
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          style={{
            fontSize: 12.5,
            padding: "6px 8px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--color-border-default)",
            background: "var(--color-background-primary, transparent)",
            color: "var(--color-text-primary)",
          }}
        >
          <option value="all">All rows</option>
          <option value="errors">Errors only</option>
          <option value="warnings">Warnings only</option>
          <option value="valid">Valid, no warnings</option>
        </select>
        <span style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginLeft: "auto" }}>
          {visibleRows.length} of {editableRows.length} row(s){sort ? ` · sorted by ${sort.column} (${sort.direction})` : ""}
        </span>
      </div>
      <div className="sheet">
        <div className="sheet-scroll" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th style={{ width: 30 }} />
                {columns.map((col) => {
                  const active = sort?.column === col.name;
                  return (
                    <th key={col.name}>
                      <button
                        type="button"
                        onClick={() => toggleSort(col.name)}
                        title={`Sort by ${col.name}`}
                        style={{
                          all: "unset",
                          cursor: "pointer",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        {col.name}
                        {col.required && <span style={{ color: "var(--color-error-500)" }}>*</span>}
                        <span style={{ fontSize: 10, color: active ? "var(--color-text-primary)" : "var(--color-text-tertiary)" }}>
                          {active ? (sort!.direction === "asc" ? "▲" : "▼") : "↕"}
                        </span>
                      </button>
                    </th>
                  );
                })}
                <th style={{ width: 36 }} />
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => {
                const { errors: rowErrors, warnings: rowWarnings } = rowLevelIssues(row);
                const rowTitle = [...rowErrors, ...rowWarnings].join(" · ") || undefined;
                const rowBg = !row.valid
                  ? "var(--color-error-50)"
                  : rowWarnings.length > 0
                    ? "var(--color-warning-50)"
                    : undefined;
                return (
                  <tr key={row.id} style={{ background: rowBg }} title={rowTitle}>
                    <td className="num" style={{ color: "var(--color-text-tertiary)" }}>
                      {!row.valid ? (
                        <span title={rowErrors.join(" · ") || "Row has an error"} style={{ color: "var(--color-error-600)", fontWeight: 800 }}>
                          !
                        </span>
                      ) : rowWarnings.length > 0 ? (
                        <span title={rowWarnings.join(" · ")} style={{ color: "var(--color-warning-600)", fontWeight: 800 }}>
                          ⚠
                        </span>
                      ) : (
                        <span style={{ color: "var(--color-success-600)" }}>✓</span>
                      )}
                    </td>
                    {columns.map((col) => {
                      const { error, warning } = cellIssues(row, col.name);
                      const value = row.values[col.name];
                      const displayValue = value === null || value === undefined ? "" : String(value);
                      const cellStyle: React.CSSProperties = {
                        width: "100%",
                        padding: "5px 7px",
                        fontSize: 12.5,
                        fontFamily: "var(--font-family-sans)",
                        border: error
                          ? "1.5px solid var(--color-error-500)"
                          : warning
                            ? "1.5px solid var(--color-warning-400)"
                            : "1px solid transparent",
                        borderRadius: "var(--radius-sm)",
                        background: error ? "var(--color-error-50)" : warning ? "var(--color-warning-50)" : "var(--color-surface-primary, transparent)",
                        color: "var(--color-text-primary)",
                      };
                      const title = error || warning || undefined;

                      return (
                        <td key={col.name} style={{ minWidth: 130 }}>
                          {col.dtype === "enum" ? (
                            <select
                              value={displayValue}
                              title={title}
                              onChange={(e) => updateCell(row.id, col.name, e.target.value)}
                              style={cellStyle}
                            >
                              <option value="" />
                              {(col.enum_values ?? []).map((ev) => (
                                <option key={ev} value={ev}>
                                  {ev}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <input
                              type={col.dtype === "int" || col.dtype === "float" ? "number" : "text"}
                              step={col.dtype === "float" ? "any" : undefined}
                              value={displayValue}
                              title={title}
                              placeholder={col.dtype === "datetime" ? "YYYY-MM-DD HH:MM" : undefined}
                              onChange={(e) => updateCell(row.id, col.name, e.target.value)}
                              style={cellStyle}
                            />
                          )}
                        </td>
                      );
                    })}
                    <td>
                      <button
                        type="button"
                        onClick={() => deleteRow(row.id)}
                        title="Delete row"
                        style={{
                          border: "none",
                          background: "transparent",
                          color: "var(--color-text-tertiary)",
                          fontWeight: 800,
                          fontSize: 14,
                          cursor: "pointer",
                          padding: "2px 6px",
                        }}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                );
              })}
              {visibleRows.length === 0 && (
                <tr>
                  <td colSpan={columns.length + 2} style={{ textAlign: "center", padding: "18px 0", color: "var(--color-text-tertiary)", fontSize: 12.5 }}>
                    No rows match the current search/filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      <button className="btn-secondary" type="button" onClick={addRow} style={{ marginTop: 10 }}>
        + Add row
      </button>
    </div>
  );
}
