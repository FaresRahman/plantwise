/** Mirrors app/core/ingestion.py:RowError / ValidationResult on the backend. */
export interface RowError {
  row: number;
  column?: string | null;
  message: string;
}

/** Mirrors core/ingestion.py:CellIssue — a single row's problem scoped to one
 * column (column === null/undefined means the issue spans the whole row,
 * e.g. a cross-column check). */
export interface CellIssue {
  column?: string | null;
  message: string;
}

/** Mirrors core/ingestion.py:ColumnMeta — describes one app field so the
 * frontend can render a typed input (number/date/dropdown/text) without
 * hardcoding per-module column definitions. */
export interface ColumnMeta {
  name: string;
  dtype: "str" | "int" | "float" | "datetime" | "enum";
  required: boolean;
  enum_values?: string[] | null;
}

/** Mirrors core/ingestion.py:RowPreview — every uploaded row (valid or not),
 * for the editable preview grid. */
export interface RowPreview {
  row: number;
  values: Record<string, unknown>;
  valid: boolean;
  errors: CellIssue[];
  warnings: CellIssue[];
}

export interface ValidationResult {
  total_rows: number;
  valid_rows: Record<string, unknown>[];
  errors: RowError[];
  warnings: RowError[];
  rows: RowPreview[];
  columns: ColumnMeta[];
  processing_time_ms?: number | null;
}

/** Mirrors core/ingestion.py:MappingSuggestion / MappingResult — the
 * auto-detected (or user-overridden) header -> app field mapping shown
 * between file upload and validation. */
export type MappingConfidence = "exact" | "case_insensitive" | "alias" | "fuzzy" | "none";

export interface MappingSuggestion {
  app_field: string;
  matched_column: string | null;
  confidence: MappingConfidence;
  required: boolean;
}

export interface MappingResult {
  headers: string[];
  mapping: MappingSuggestion[];
  columns: ColumnMeta[];
}

/** Mirrors core/ingestion.py:commit_response — always surfaces what was
 * skipped and why, even on a successful commit. */
export interface CommitResult {
  committed: number;
  skipped: number;
  errors: RowError[];
  warnings: RowError[];
  updated?: number;
  processing_time_ms?: number;
}
