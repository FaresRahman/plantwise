"""Oracle Database adapter — uses python-oracledb in thin mode (pure
Python, no Oracle Instant Client install required) with its native asyncio
support (oracledb.connect_async).

Not verified against a live Oracle instance (none available in this
environment) — built to python-oracledb's documented async API and Oracle's
standard ALL_* data dictionary views; treat as needing a real-server smoke
test before relying on it in production.
"""
from __future__ import annotations

import oracledb

from db_adapters.base import (
    AdapterError,
    ColumnInfo,
    ConnectionParams,
    DatabaseAdapter,
    TableInfo,
    quote_ident,
)
from db_adapters.registry import register_adapter

MAX_IMPORT_ROWS = 50_000


@register_adapter
class OracleAdapter(DatabaseAdapter):
    engine_key = "oracle"
    display_name = "Oracle Database"
    tier = 1
    default_ports = (1521,)
    prerequisite_note = None  # thin mode: no Oracle Instant Client needed

    def __init__(self, params: ConnectionParams):
        super().__init__(params)
        self._conn: oracledb.AsyncConnection | None = None

    async def _connect(self) -> oracledb.AsyncConnection:
        if self._conn is None:
            if not self.params.database:
                raise AdapterError("Oracle requires a service name in the Database Name field to connect.")
            dsn = f"{self.params.host}:{self.params.port}/{self.params.database}"
            try:
                self._conn = await oracledb.connect_async(
                    user=self.params.username,
                    password=self.params.password,
                    dsn=dsn,
                    tcp_connect_timeout=self.params.connect_timeout_seconds,
                )
            except oracledb.Error as exc:
                raise AdapterError(f"Could not connect as Oracle: {exc}") from exc
        return self._conn

    async def _fetch(self, sql: str, args: tuple = ()) -> list[dict]:
        conn = await self._connect()
        cur = conn.cursor()
        try:
            await cur.execute(sql, args)
            cols = [d[0] for d in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]
        finally:
            # AsyncCursor.close() is synchronous in oracledb's async API
            # (unlike AsyncConnection.close()/.commit() and
            # AsyncCursor.execute()/.fetchall(), which are all coroutines) —
            # awaiting it raises "'NoneType' object can't be awaited" on
            # every call, since close() returns None, not a coroutine.
            cur.close()

    async def test_connection(self) -> dict:
        rows = await self._fetch("SELECT banner FROM v$version WHERE ROWNUM = 1")
        return {"version": rows[0]["BANNER"] if rows else "Oracle Database"}

    async def discover_schemas(self) -> list[str]:
        rows = await self._fetch("SELECT username FROM all_users ORDER BY username")
        return [r["USERNAME"] for r in rows]

    async def discover_tables(self, schema: str | None) -> list[TableInfo]:
        owner = (schema or self.params.username).upper()
        rows = await self._fetch(
            "SELECT owner, table_name, num_rows FROM all_tables WHERE owner = :1 ORDER BY table_name",
            (owner,),
        )
        return [TableInfo(schema=r["OWNER"], name=r["TABLE_NAME"], row_count_estimate=r["NUM_ROWS"]) for r in rows]

    async def discover_columns(self, schema: str | None, table: str) -> list[ColumnInfo]:
        owner = (schema or self.params.username).upper()
        rows = await self._fetch(
            "SELECT column_name, data_type, nullable FROM all_tab_columns "
            "WHERE owner = :1 AND table_name = :2 ORDER BY column_id",
            (owner, table.upper()),
        )
        return [ColumnInfo(name=r["COLUMN_NAME"], source_type=r["DATA_TYPE"], nullable=r["NULLABLE"] == "Y") for r in rows]

    async def _select(self, schema: str | None, table: str, limit: int) -> list[dict]:
        owner = (schema or self.params.username).upper()
        qualified = f"{quote_ident(owner)}.{quote_ident(table.upper())}"
        return await self._fetch(f"SELECT * FROM {qualified} FETCH FIRST :1 ROWS ONLY", (limit,))

    async def sample_rows(self, schema: str | None, table: str, limit: int = 25) -> list[dict]:
        return await self._select(schema, table, limit)

    async def read_rows(self, schema: str | None, table: str, limit: int | None = None) -> list[dict]:
        return await self._select(schema, table, min(limit, MAX_IMPORT_ROWS) if limit else MAX_IMPORT_ROWS)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
