"""Generic bulk-upload validation engine, parameterized per module. Build one
uploader, configure it per module — don't hand-roll a bespoke parser for each
of the 4 data modules. Accepts CSV or Excel (.xlsx) — plant staff commonly
keep this data in spreadsheets, so we don't force a CSV-only workflow.

Pattern for a module's operational-data upload (see DEV_BRIEF section 4.4):
    1. GET  /{module}/csv/template   -> the header row, for download
    2. POST /{module}/csv/map        -> map_csv_columns(...), detects headers +
                                         suggests an app-field mapping, nothing
                                         validated/committed
    3. POST /{module}/csv/validate   -> validate_csv(...), nothing committed
    4. POST /{module}/csv/commit     -> insert valid rows (either re-parsed from
                                         the file, or from an edited preview
                                         grid via edited_rows), then
                                         touch_freshness(...)
"""
import difflib
import io
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import pandas as pd
from fastapi import HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models_shared import ModuleFreshness

DType = Literal["str", "int", "float", "datetime", "enum"]

# Common alternate spellings for app fields shared across modules — deliberately
# small and generic (module-specific specs can't register their own aliases
# without importing this module, so this stays a flat, hand-curated table).
# Deterministic matching (exact -> case/whitespace-insensitive -> alias ->
# fuzzy) is tried in that order before a column is left unmapped; per the
# import spec, an AI fallback is intentionally not wired in here — low-
# confidence matches are surfaced to the user to resolve instead.
FIELD_ALIASES: dict[str, list[str]] = {
    "asset_code": ["asset id", "equipment code", "equipment id", "code"],
    "sku": ["item code", "item id", "part number", "part no"],
    "line_code": ["line id", "production line", "line"],
    "line_id": ["line code", "line"],
    "part_id": ["part number", "part no", "part"],
    "name": ["description", "title"],
    "timestamp": ["date", "datetime", "time", "reading date"],
    "install_date": ["installed on", "installation date", "date installed"],
    "line_area": ["area", "location"],
    "criticality": ["priority"],
    "category": ["asset category", "type"],
    "reorder_point": ["reorder qty", "min stock", "minimum stock"],
    "supplier_lead_time_days": ["lead time", "lead time days", "lead time (days)"],
    "unit_of_measure": ["uom", "unit"],
    "item_type": ["type"],
    "shift_target_units": ["shift target", "target units"],
    "ideal_cycle_time_seconds": ["cycle time", "ideal cycle time"],
    "nominal_value": ["nominal", "target value"],
    "tolerance": ["tol"],
    "inspection_type": ["inspection method"],
    "characteristic_name": ["characteristic", "feature"],
    "measured_value": ["measurement", "value"],
    "pass_fail": ["result"],
    "defect_type": ["defect", "defect category"],
    "current_qty": ["quantity", "qty on hand", "on hand"],
    "qty_in": ["quantity in", "received"],
    "qty_out": ["quantity out", "consumed", "issued"],
    "movement_reason": ["reason"],
    "downtime_minutes": ["downtime", "downtime (min)"],
    "downtime_reason": ["reason", "stop reason"],
    "units_produced": ["produced", "total produced"],
    "units_good": ["good units", "good"],
    "units_reject": ["reject units", "rejects", "scrap"],
    "start_time": ["shift start"],
    "end_time": ["shift end"],
    "areas": ["area", "coverage"],
    "recipients": ["email", "emails", "notify"],
}


@dataclass
class ColumnSpec:
    name: str
    dtype: DType = "str"
    required: bool = True
    enum_values: list[str] | None = None


@dataclass
class CSVSpec:
    module: str
    columns: list[ColumnSpec]
    # column name -> async (db, tenant_id, value) -> bool ; used for referential
    # integrity checks (e.g. an asset_id/sku/line_id must already exist)
    fk_checks: dict[str, Callable[[AsyncSession, int, str], Awaitable[bool]]] = field(default_factory=dict)
    # async (db, tenant_id, parsed_row) -> error message | None ; for checks that
    # span more than one column (e.g. a station_id must belong to the specific
    # line_id named in the same row) — fk_checks only sees a single column's value.
    row_checks: list[Callable[[AsyncSession, int, dict], Awaitable[str | None]]] = field(default_factory=list)
    # async (db, tenant_id, parsed_row) -> warning message | None ; non-blocking
    # checks that don't invalidate the row (e.g. "this record already exists —
    # will be updated on commit"). Warnings are surfaced in ValidationResult
    # separately from errors so the frontend can show them as amber/info alerts.
    row_warnings: list[Callable[[AsyncSession, int, dict], Awaitable[str | None]]] = field(default_factory=list)


class RowError(BaseModel):
    row: int
    column: str | None = None
    message: str


class CellIssue(BaseModel):
    column: str | None = None
    message: str


class ColumnMeta(BaseModel):
    name: str
    dtype: DType
    required: bool
    enum_values: list[str] | None = None


class RowPreview(BaseModel):
    """One row's worth of data for the editable preview grid — unlike
    valid_rows (which only carries rows that passed every check), this
    includes every row, valid or not, so the grid can show and let the user
    fix invalid rows in place instead of only reporting them as skipped.
    """
    row: int
    values: dict
    valid: bool
    errors: list[CellIssue] = []
    warnings: list[CellIssue] = []


class ValidationResult(BaseModel):
    total_rows: int
    valid_rows: list[dict]
    errors: list[RowError]
    warnings: list[RowError] = []
    rows: list[RowPreview] = []
    columns: list[ColumnMeta] = []
    # Wall-clock time spent validating (coercion + fk/row checks), in
    # milliseconds — surfaced in the import summary (commit_response) below.
    # Covers _validate_records only, not file-parsing or the actual DB
    # writes a commit endpoint does afterward with result.valid_rows.
    processing_time_ms: float | None = None


MappingConfidence = Literal["exact", "case_insensitive", "alias", "fuzzy", "none"]


class MappingSuggestion(BaseModel):
    app_field: str
    matched_column: str | None
    confidence: MappingConfidence
    required: bool


class MappingResult(BaseModel):
    headers: list[str]
    mapping: list[MappingSuggestion]
    columns: list[ColumnMeta]


def _coerce(value, dtype: DType, column: str, row_number: int, enum_values: list[str] | None, errors: list[RowError]):
    if pd.isna(value):
        return None
    try:
        if dtype == "int":
            return int(value)
        if dtype == "float":
            return float(value)
        if dtype == "datetime":
            return pd.to_datetime(value).to_pydatetime()
        if dtype == "enum":
            sval = str(value).strip()
            if enum_values and sval not in enum_values:
                errors.append(
                    RowError(row=row_number, column=column, message=f"'{sval}' not one of {enum_values}")
                )
                return None
            return sval
        return str(value).strip()
    except (ValueError, TypeError):
        errors.append(RowError(row=row_number, column=column, message=f"could not parse '{value}' as {dtype}"))
        return None


def _read_table(content: bytes, filename: str) -> pd.DataFrame:
    """CSV or Excel (.xlsx/.xls) — detected by extension, falling back to CSV
    if the filename is missing/unrecognized (e.g. a client that doesn't send
    one). Plant staff commonly keep this data in spreadsheets, so both are
    first-class, not just CSV.
    """
    lower = (filename or "").lower()
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        return pd.read_excel(io.BytesIO(content))
    return pd.read_csv(io.BytesIO(content))


def _spec_columns_meta(spec: CSVSpec) -> list[ColumnMeta]:
    return [ColumnMeta(name=c.name, dtype=c.dtype, required=c.required, enum_values=c.enum_values) for c in spec.columns]


def _row_display_values(spec: CSVSpec, raw_row: dict, parsed: dict) -> dict:
    """Build the JSON-safe {app_field: value} dict shown/edited in the preview
    grid — the coerced value where parsing succeeded, otherwise the raw
    uploaded value (stringified) so an invalid cell still shows what the user
    typed rather than going blank.
    """
    values: dict = {}
    for col in spec.columns:
        if col.name in parsed:
            v = parsed[col.name]
            values[col.name] = v.isoformat() if hasattr(v, "isoformat") else v
        else:
            raw_v = raw_row.get(col.name)
            values[col.name] = None if raw_v is None or pd.isna(raw_v) else str(raw_v)
    return values


async def _validate_records(records: list[dict], spec: CSVSpec, db: AsyncSession, tenant_id: int) -> ValidationResult:
    started_at = time.perf_counter()
    errors: list[RowError] = []
    warnings: list[RowError] = []
    valid_rows: list[dict] = []
    rows: list[RowPreview] = []

    for i, raw_row in enumerate(records):
        row_number = i + 2  # +1 header row, +1 to make it 1-indexed for humans
        local_errors: list[RowError] = []
        local_warnings: list[RowError] = []
        parsed: dict = {}
        for col in spec.columns:
            value = raw_row.get(col.name)
            if (value is None or pd.isna(value)) and col.required:
                local_errors.append(RowError(row=row_number, column=col.name, message="required value missing"))
                continue
            if value is None:
                continue
            parsed[col.name] = _coerce(value, col.dtype, col.name, row_number, col.enum_values, local_errors)

        for column, checker in spec.fk_checks.items():
            value = parsed.get(column)
            if value is not None and not await checker(db, tenant_id, value):
                local_errors.append(RowError(row=row_number, column=column, message=f"unknown reference '{value}'"))

        for row_checker in spec.row_checks:
            message = await row_checker(db, tenant_id, parsed)
            if message:
                local_errors.append(RowError(row=row_number, column=None, message=message))

        if not local_errors:
            for warning_checker in spec.row_warnings:
                message = await warning_checker(db, tenant_id, parsed)
                if message:
                    local_warnings.append(RowError(row=row_number, column=None, message=message))
            valid_rows.append(parsed)

        errors.extend(local_errors)
        warnings.extend(local_warnings)
        rows.append(
            RowPreview(
                row=row_number,
                values=_row_display_values(spec, raw_row, parsed),
                valid=not local_errors,
                errors=[CellIssue(column=e.column, message=e.message) for e in local_errors],
                warnings=[CellIssue(column=w.column, message=w.message) for w in local_warnings],
            )
        )

    return ValidationResult(
        total_rows=len(records),
        valid_rows=valid_rows,
        errors=errors,
        warnings=warnings,
        rows=rows,
        columns=_spec_columns_meta(spec),
        processing_time_ms=(time.perf_counter() - started_at) * 1000,
    )


async def validate_records(records: list[dict], spec: CSVSpec, db: AsyncSession, tenant_id: int) -> ValidationResult:
    """Validate rows that didn't come from a freshly-uploaded file — e.g. rows
    a user edited in the preview grid before confirming import. Same checks
    (required/dtype/enum/fk/row) as validate_csv, just skipping the
    file-parsing step.
    """
    return await _validate_records(records, spec, db, tenant_id)


async def validate_csv(
    content: bytes,
    filename: str,
    spec: CSVSpec,
    db: AsyncSession,
    tenant_id: int,
    column_mapping: dict[str, str | None] | None = None,
) -> ValidationResult:
    try:
        df = _read_table(content, filename)
    except Exception as exc:  # malformed file entirely
        return ValidationResult(
            total_rows=0, valid_rows=[], errors=[RowError(row=0, message=f"could not parse file: {exc}")],
            columns=_spec_columns_meta(spec),
        )

    df.columns = [str(c).strip() for c in df.columns]
    if column_mapping:
        # column_mapping: app_field -> uploaded header name (or None/omitted if
        # unmapped) — from either the /csv/{entity}/map suggestion or the
        # user's own override of it. Rename before the rest of validation runs
        # so everything downstream can keep referring to app field names.
        rename = {uploaded: app_field for app_field, uploaded in column_mapping.items() if uploaded}
        df = df.rename(columns=rename)

    required_cols = [c.name for c in spec.columns if c.required]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        return ValidationResult(
            total_rows=len(df),
            valid_rows=[],
            errors=[RowError(row=0, message=f"missing required column(s): {', '.join(missing)}")],
            columns=_spec_columns_meta(spec),
        )

    records = df.to_dict(orient="records")
    return await _validate_records(records, spec, db, tenant_id)


# ---------------------------------------------------------------------------
# Auto field mapping (deterministic: exact -> case/whitespace-insensitive ->
# alias -> fuzzy). Runs before validation so an uploaded file whose headers
# don't literally match the app's column names can still be mapped instead of
# failing outright with "missing required column(s)".
# ---------------------------------------------------------------------------

def _normalize_header(s: str) -> str:
    return "".join(ch for ch in s.lower().strip() if ch.isalnum())


def auto_map_columns(headers: list[str], spec: CSVSpec) -> list[MappingSuggestion]:
    normalized_headers = {_normalize_header(h): h for h in headers}
    used: set[str] = set()
    suggestions: list[MappingSuggestion] = []

    for col in spec.columns:
        target: str | None = None
        confidence: MappingConfidence = "none"

        if col.name in headers and col.name not in used:
            target, confidence = col.name, "exact"
        elif _normalize_header(col.name) in normalized_headers and normalized_headers[_normalize_header(col.name)] not in used:
            target, confidence = normalized_headers[_normalize_header(col.name)], "case_insensitive"
        else:
            for alias in FIELD_ALIASES.get(col.name, []):
                candidate = normalized_headers.get(_normalize_header(alias))
                if candidate is not None and candidate not in used:
                    target, confidence = candidate, "alias"
                    break

        if target is None:
            remaining = [h for h in headers if h not in used]
            close = difflib.get_close_matches(col.name, remaining, n=1, cutoff=0.6)
            if close:
                target, confidence = close[0], "fuzzy"

        if target is not None:
            used.add(target)
        suggestions.append(
            MappingSuggestion(app_field=col.name, matched_column=target, confidence=confidence, required=col.required)
        )

    return suggestions


def detect_headers(content: bytes, filename: str) -> list[str]:
    df = _read_table(content, filename)
    return [str(c).strip() for c in df.columns]


async def map_csv_columns(content: bytes, filename: str, spec: CSVSpec) -> MappingResult:
    try:
        headers = detect_headers(content, filename)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"could not parse file: {exc}")
    return MappingResult(headers=headers, mapping=auto_map_columns(headers, spec), columns=_spec_columns_meta(spec))


# ---------------------------------------------------------------------------
# Commit-time row resolution — a commit either re-parses the originally
# uploaded file (optionally with a column mapping), or takes edited_rows: a
# JSON array of {app_field: value} objects the user edited in the preview
# grid. Either way it's revalidated from scratch here rather than trusting
# whatever validate_csv returned earlier in the flow.
# ---------------------------------------------------------------------------

async def resolve_commit_validation(
    spec: CSVSpec,
    db: AsyncSession,
    tenant_id: int,
    file: UploadFile | None,
    edited_rows: str | None,
    column_mapping: dict[str, str | None] | None = None,
) -> ValidationResult:
    if edited_rows is not None:
        try:
            records = json.loads(edited_rows)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"edited_rows is not valid JSON: {exc}")
        if not isinstance(records, list):
            raise HTTPException(status_code=422, detail="edited_rows must be a JSON array of row objects")
        return await validate_records(records, spec, db, tenant_id)
    if file is None:
        raise HTTPException(status_code=422, detail="file or edited_rows is required")
    content = await file.read()
    return await validate_csv(content, file.filename or "", spec, db, tenant_id, column_mapping=column_mapping)


def enforce_commit_gate(result: ValidationResult, skip_invalid: bool) -> None:
    """Commit contract (DEV_BRIEF/PRD 5.4): nothing commits until errors are
    resolved OR the caller explicitly opts to skip the offending rows. Call
    this before inserting any row in a module's /commit endpoint — if it
    raises, the caller must re-validate/fix the file or resubmit with
    skip_invalid=true.
    """
    if result.errors and not skip_invalid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    f"{len(result.errors)} row(s) failed validation — fix them and resubmit, "
                    "or resubmit with skip_invalid=true to commit only the valid rows."
                ),
                "errors": [e.model_dump() for e in result.errors],
            },
        )


def commit_response(result: ValidationResult, committed: int, updated: int = 0) -> dict:
    """Standard commit response — always surfaces what was skipped and why,
    even when skip_invalid=true let the errors through. A bare {"committed": N}
    silently hides validation failures from the caller/audit trail.

    For config imports that support upsert, pass ``updated`` to report how many
    existing records were updated vs newly created.
    """
    response: dict = {
        "committed": committed,
        "skipped": len(result.errors),
        "errors": [e.model_dump() for e in result.errors],
        "warnings": [w.model_dump() for w in result.warnings],
    }
    if updated:
        response["updated"] = updated
    if result.processing_time_ms is not None:
        response["processing_time_ms"] = round(result.processing_time_ms, 1)
    return response


async def touch_freshness(db: AsyncSession, tenant_id: int, module: str) -> None:
    row = await db.scalar(
        select(ModuleFreshness).where(ModuleFreshness.tenant_id == tenant_id, ModuleFreshness.module == module)
    )
    # Naive UTC to match ModuleFreshness.last_updated_at's plain DateTime column —
    # asyncpg rejects an offset-aware datetime against a TIMESTAMP WITHOUT TIME
    # ZONE column outright. Using .replace(tzinfo=None) rather than the
    # deprecated datetime.utcnow().
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if row:
        row.last_updated_at = now
    else:
        db.add(ModuleFreshness(tenant_id=tenant_id, module=module, last_updated_at=now))
    await db.commit()
