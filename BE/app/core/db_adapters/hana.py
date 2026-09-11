"""SAP HANA adapter — uses hdbcli, SAP's official pure-Python driver (no
separate native client library needed). hdbcli is synchronous, so every
call is wrapped in asyncio.to_thread.

Not verified against a live HANA instance (none available in this
environment) — built to hdbcli's documented DB-API and HANA's SYS.* system
views; treat as needing a real-server smoke test before relying on it in
production.
"""
from __future__ import annotations

import asyncio

from hdbcli import dbapi as hana_dbapi

from app.core.db_adapters.base import (
    AdapterError,
    ColumnInfo,
    ConnectionParams,
    DatabaseAdapter,
    TableInfo,
    quote_ident,
)
from app.core.db_adapters.registry import register_adapter

MAX_IMPORT_ROWS = 50_000


@register_adapter
class HanaAdapter(DatabaseAdapter):
    engine_key = "hana"
    display_name = "SAP HANA"
    tier = 1
    default_ports = (30015, 30013, 30041)

    def __init__(self, params: ConnectionParams):
        super().__init__(params)
        self._conn = None

    def _sync_connect(self):
        if self._conn is None:
            try:
                self._conn = hana_dbapi.connect(
                    address=self.params.host,
                    port=self.params.port,
                    user=self.params.username,
                    password=self.params.password,
                    encrypt=self.params.ssl,
                    sslValidateCertificate=False,
                    communicationTimeout=int(self.params.connect_timeout_seconds * 1000),
                )
            except Exception as exc:  # hdbcli raises its own dbapi.Error hierarchy
                raise AdapterError(f"Could not connect as SAP HANA: {exc}") from exc
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
        rows = await self._fetch("SELECT VERSION FROM SYS.M_DATABASE")
        return {"version": f"SAP HANA {rows[0]['VERSION']}" if rows else "SAP HANA"}

    async def discover_schemas(self) -> list[str]:
        rows = await self._fetch(
            "SELECT SCHEMA_NAME FROM SYS.SCHEMAS "
            "WHERE SCHEMA_NAME NOT LIKE '\\_SYS%' ESCAPE '\\' AND SCHEMA_NAME NOT IN ('SYS', 'PUBLIC') "
            "ORDER BY 1"
        )
        return [r["SCHEMA_NAME"] for r in rows]

    async def discover_tables(self, schema: str | None) -> list[TableInfo]:
        schemas = [schema] if schema else await self.discover_schemas()
        placeholders = ",".join("?" for _ in schemas)
        rows = await self._fetch(
            f"SELECT SCHEMA_NAME, TABLE_NAME, RECORD_COUNT FROM SYS.M_TABLES "
            f"WHERE SCHEMA_NAME IN ({placeholders}) ORDER BY SCHEMA_NAME, TABLE_NAME",
            tuple(schemas),
        )
        return [
            TableInfo(schema=r["SCHEMA_NAME"], name=r["TABLE_NAME"], row_count_estimate=r["RECORD_COUNT"])
            for r in rows
        ]

    async def discover_columns(self, schema: str | None, table: str) -> list[ColumnInfo]:
        owner = schema or self.params.username.upper()
        rows = await self._fetch(
            "SELECT COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE FROM SYS.TABLE_COLUMNS "
            "WHERE SCHEMA_NAME = ? AND TABLE_NAME = ? ORDER BY POSITION",
            (owner, table),
        )
        return [
            ColumnInfo(name=r["COLUMN_NAME"], source_type=r["DATA_TYPE_NAME"], nullable=r["IS_NULLABLE"] == "TRUE")
            for r in rows
        ]

    async def _select(self, schema: str | None, table: str, limit: int) -> list[dict]:
        owner = schema or self.params.username.upper()
        qualified = f"{quote_ident(owner)}.{quote_ident(table)}"
        return await self._fetch(f"SELECT * FROM {qualified} LIMIT {int(limit)}")

    async def sample_rows(self, schema: str | None, table: str, limit: int = 25) -> list[dict]:
        return await self._select(schema, table, limit)

    async def read_rows(self, schema: str | None, table: str, limit: int | None = None) -> list[dict]:
        return await self._select(schema, table, min(limit, MAX_IMPORT_ROWS) if limit else MAX_IMPORT_ROWS)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None
