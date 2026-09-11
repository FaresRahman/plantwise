"""SQL Server adapter — also covers Azure SQL Database (same TDS wire
protocol). Uses python-tds (pure Python, no ODBC driver install required),
which is a synchronous DB-API driver — every call is wrapped in
asyncio.to_thread so it never blocks the event loop.

Not verified against a live SQL Server instance (none available in this
environment) — built to python-tds's documented API and T-SQL's standard
INFORMATION_SCHEMA views; treat as needing a real-server smoke test before
relying on it in production.
"""
from __future__ import annotations

import asyncio

import pytds

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
_SYSTEM_SCHEMAS = (
    "sys", "INFORMATION_SCHEMA", "guest", "db_owner", "db_accessadmin", "db_securityadmin",
    "db_ddladmin", "db_backupoperator", "db_datareader", "db_datawriter", "db_denydatareader",
    "db_denydatawriter",
)


@register_adapter
class MSSQLAdapter(DatabaseAdapter):
    engine_key = "mssql"
    display_name = "Microsoft SQL Server"
    tier = 1
    default_ports = (1433,)

    def __init__(self, params: ConnectionParams):
        super().__init__(params)
        self._conn: pytds.Connection | None = None

    def _sync_connect(self) -> pytds.Connection:
        if self._conn is None:
            try:
                self._conn = pytds.connect(
                    server=self.params.host,
                    port=self.params.port,
                    database=self.params.database,
                    user=self.params.username,
                    password=self.params.password,
                    login_timeout=int(self.params.connect_timeout_seconds),
                    timeout=int(self.params.connect_timeout_seconds),
                    as_dict=True,
                    validate_host=False,
                )
            except Exception as exc:  # pytds raises its own exception hierarchy
                raise AdapterError(f"Could not connect as SQL Server: {exc}") from exc
        return self._conn

    def _sync_fetch(self, sql: str, args: tuple = ()) -> list[dict]:
        conn = self._sync_connect()
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return list(cur.fetchall())

    async def _fetch(self, sql: str, args: tuple = ()) -> list[dict]:
        return await asyncio.to_thread(self._sync_fetch, sql, args)

    async def test_connection(self) -> dict:
        rows = await self._fetch("SELECT @@VERSION AS version")
        version = str(rows[0]["version"]).splitlines()[0] if rows else "SQL Server"
        return {"version": version}

    async def discover_schemas(self) -> list[str]:
        placeholders = ",".join("%s" for _ in _SYSTEM_SCHEMAS)
        rows = await self._fetch(
            f"SELECT schema_name FROM information_schema.schemata "
            f"WHERE schema_name NOT IN ({placeholders}) ORDER BY 1",
            _SYSTEM_SCHEMAS,
        )
        return [r["schema_name"] for r in rows]

    async def discover_tables(self, schema: str | None) -> list[TableInfo]:
        schemas = [schema] if schema else await self.discover_schemas()
        placeholders = ",".join("%s" for _ in schemas)
        rows = await self._fetch(
            f"SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS table_name FROM information_schema.tables "
            f"WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA IN ({placeholders}) "
            f"ORDER BY TABLE_SCHEMA, TABLE_NAME",
            tuple(schemas),
        )
        return [TableInfo(schema=r["schema_name"], name=r["table_name"]) for r in rows]

    async def discover_columns(self, schema: str | None, table: str) -> list[ColumnInfo]:
        rows = await self._fetch(
            "SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type, IS_NULLABLE AS is_nullable "
            "FROM information_schema.columns WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION",
            (schema or "dbo", table),
        )
        return [ColumnInfo(name=r["column_name"], source_type=r["data_type"], nullable=r["is_nullable"] == "YES") for r in rows]

    async def _select(
        self, schema: str | None, table: str, limit: int, since_column: str | None = None, since_value: object = None
    ) -> list[dict]:
        qualified = f"{quote_ident(schema or 'dbo')}.{quote_ident(table)}"
        if since_column and since_value is not None:
            col = quote_ident(since_column)
            return await self._fetch(
                f"SELECT TOP {int(limit)} * FROM {qualified} WHERE {col} > %s ORDER BY {col} ASC", (since_value,)
            )
        return await self._fetch(f"SELECT TOP {int(limit)} * FROM {qualified}")

    async def sample_rows(self, schema: str | None, table: str, limit: int = 25) -> list[dict]:
        return await self._select(schema, table, limit)

    async def read_rows(
        self, schema: str | None, table: str, limit: int | None = None,
        since_column: str | None = None, since_value: object = None,
    ) -> list[dict]:
        return await self._select(
            schema, table, min(limit, MAX_IMPORT_ROWS) if limit else MAX_IMPORT_ROWS, since_column, since_value
        )

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None
