"""SQLite adapter — file-based, so it's only ever reachable through the
Local Connector (which runs on the same machine as the file), never through
Cloud Database Import (which needs a host:port to reach). ConnectionParams
.database holds the file path here; host/port/username/password are
ignored (SQLite has no network auth).
"""
from __future__ import annotations

import asyncio
import sqlite3

from db_adapters.base import AdapterError, ColumnInfo, ConnectionParams, DatabaseAdapter, TableInfo, quote_ident
from db_adapters.registry import register_adapter

MAX_IMPORT_ROWS = 50_000


@register_adapter
class SqliteAdapter(DatabaseAdapter):
    engine_key = "sqlite"
    display_name = "SQLite"
    tier = 1
    default_ports = ()
    local_only = True

    def __init__(self, params: ConnectionParams):
        super().__init__(params)
        self._conn: sqlite3.Connection | None = None

    def _sync_connect(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self.params.database:
                raise AdapterError("SQLite requires a file path in the Database Name field.")
            try:
                self._conn = sqlite3.connect(self.params.database)
                self._conn.row_factory = sqlite3.Row
            except sqlite3.Error as exc:
                raise AdapterError(f"Could not open SQLite file: {exc}") from exc
        return self._conn

    def _sync_fetch(self, sql: str, args: tuple = ()) -> list[dict]:
        conn = self._sync_connect()
        cur = conn.execute(sql, args)
        return [dict(row) for row in cur.fetchall()]

    async def _fetch(self, sql: str, args: tuple = ()) -> list[dict]:
        return await asyncio.to_thread(self._sync_fetch, sql, args)

    async def test_connection(self) -> dict:
        rows = await self._fetch("SELECT sqlite_version() AS version")
        return {"version": f"SQLite {rows[0]['version']}"}

    async def discover_schemas(self) -> list[str]:
        return ["main"]

    async def discover_tables(self, schema: str | None) -> list[TableInfo]:
        rows = await self._fetch(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [TableInfo(schema="main", name=r["name"]) for r in rows]

    async def discover_columns(self, schema: str | None, table: str) -> list[ColumnInfo]:
        rows = await self._fetch(f"PRAGMA table_info({quote_ident(table)})")
        return [ColumnInfo(name=r["name"], source_type=r["type"] or "TEXT", nullable=not r["notnull"]) for r in rows]

    async def _select(
        self, table: str, limit: int, since_column: str | None = None, since_value: object = None
    ) -> list[dict]:
        if since_column and since_value is not None:
            col = quote_ident(since_column)
            return await self._fetch(
                f"SELECT * FROM {quote_ident(table)} WHERE {col} > ? ORDER BY {col} ASC LIMIT ?", (since_value, limit)
            )
        return await self._fetch(f"SELECT * FROM {quote_ident(table)} LIMIT ?", (limit,))

    async def sample_rows(self, schema: str | None, table: str, limit: int = 25) -> list[dict]:
        return await self._select(table, limit)

    async def read_rows(
        self, schema: str | None, table: str, limit: int | None = None,
        since_column: str | None = None, since_value: object = None,
    ) -> list[dict]:
        return await self._select(table, min(limit, MAX_IMPORT_ROWS) if limit else MAX_IMPORT_ROWS, since_column, since_value)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None
