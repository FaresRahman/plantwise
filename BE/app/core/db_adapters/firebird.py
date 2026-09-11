"""Firebird adapter — tier 2: requires the firebird-driver package plus the
Firebird client library (fbclient) installed on whatever machine runs the
import service. Not installed by default (see BE/requirements.txt) — until
`firebird-driver` is installed, every call raises PrerequisiteMissingError
so the UI shows a clear "not ready" notice instead of a raw connection
failure.

Not verified against a live Firebird instance (none available in this
environment, and the driver isn't installed here either) — built to
firebird-driver's documented API and Firebird's rdb$ system tables.
"""
from __future__ import annotations

import asyncio

from app.core.db_adapters.base import (
    AdapterError,
    ColumnInfo,
    ConnectionParams,
    DatabaseAdapter,
    PrerequisiteMissingError,
    TableInfo,
    quote_ident,
)
from app.core.db_adapters.registry import register_adapter

MAX_IMPORT_ROWS = 50_000
_PREREQUISITE_NOTE = (
    "Requires the firebird-driver package and the Firebird client library (fbclient) on the server. "
    "Run `pip install firebird-driver`, install the Firebird client, and restart the import service."
)


@register_adapter
class FirebirdAdapter(DatabaseAdapter):
    engine_key = "firebird"
    display_name = "Firebird"
    tier = 2
    default_ports = (3050,)
    prerequisite_note = _PREREQUISITE_NOTE

    def __init__(self, params: ConnectionParams):
        super().__init__(params)
        self._conn = None

    @staticmethod
    def _driver():
        try:
            import firebird.driver as fb
        except ImportError as exc:
            raise PrerequisiteMissingError(_PREREQUISITE_NOTE) from exc
        return fb

    def _sync_connect(self):
        fb = self._driver()
        if self._conn is None:
            dsn = f"{self.params.host}/{self.params.port}:{self.params.database}"
            try:
                self._conn = fb.connect(dsn, user=self.params.username, password=self.params.password)
            except Exception as exc:
                # firebird-driver raises a bare Exception (no distinct type)
                # both for "can't find the native fbclient library" and for
                # genuine connection failures — the former is a prerequisite
                # problem (same class as the driver not being pip-installed
                # at all), not a bad host/port/credential, so it needs the
                # same PrerequisiteMissingError treatment for detect_engine's
                # port-match auto-detection to explain it correctly.
                if "client library" in str(exc).lower():
                    raise PrerequisiteMissingError(
                        f"{_PREREQUISITE_NOTE} ({exc})"
                    ) from exc
                raise AdapterError(f"Could not connect as Firebird: {exc}") from exc
        return self._conn

    def _sync_fetch(self, sql: str, args: tuple = ()) -> list[dict]:
        conn = self._sync_connect()
        cur = conn.cursor()
        try:
            cur.execute(sql, args)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            cur.close()

    async def _fetch(self, sql: str, args: tuple = ()) -> list[dict]:
        return await asyncio.to_thread(self._sync_fetch, sql, args)

    async def test_connection(self) -> dict:
        rows = await self._fetch("SELECT rdb$get_context('SYSTEM', 'ENGINE_VERSION') AS version FROM rdb$database")
        return {"version": f"Firebird {rows[0]['VERSION']}" if rows else "Firebird"}

    async def discover_schemas(self) -> list[str]:
        # Firebird has no schema concept — one flat namespace per database.
        # Report a single pseudo-schema so the rest of the pipeline (which
        # always deals in schema+table) doesn't need a Firebird special case.
        return [self.params.database or "default"]

    async def discover_tables(self, schema: str | None) -> list[TableInfo]:
        rows = await self._fetch(
            "SELECT TRIM(rdb$relation_name) AS table_name FROM rdb$relations "
            "WHERE rdb$view_blr IS NULL AND (rdb$system_flag IS NULL OR rdb$system_flag = 0) "
            "ORDER BY 1"
        )
        pseudo_schema = self.params.database or "default"
        return [TableInfo(schema=pseudo_schema, name=r["TABLE_NAME"]) for r in rows]

    async def discover_columns(self, schema: str | None, table: str) -> list[ColumnInfo]:
        rows = await self._fetch(
            "SELECT TRIM(rf.rdb$field_name) AS column_name, f.rdb$field_type AS data_type, "
            "rf.rdb$null_flag AS not_null "
            "FROM rdb$relation_fields rf JOIN rdb$fields f ON f.rdb$field_name = rf.rdb$field_source "
            "WHERE rf.rdb$relation_name = ? ORDER BY rf.rdb$field_position",
            (table.upper(),),
        )
        return [
            ColumnInfo(name=r["COLUMN_NAME"], source_type=str(r["DATA_TYPE"]), nullable=not r["NOT_NULL"])
            for r in rows
        ]

    async def _select(self, table: str, limit: int) -> list[dict]:
        return await self._fetch(f"SELECT FIRST {int(limit)} * FROM {quote_ident(table.upper())}")

    async def sample_rows(self, schema: str | None, table: str, limit: int = 25) -> list[dict]:
        return await self._select(table, limit)

    async def read_rows(self, schema: str | None, table: str, limit: int | None = None) -> list[dict]:
        return await self._select(table, min(limit, MAX_IMPORT_ROWS) if limit else MAX_IMPORT_ROWS)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None
