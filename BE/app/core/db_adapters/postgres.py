"""PostgreSQL adapter — also the wire protocol behind CockroachDB,
YugabyteDB, Amazon Aurora (Postgres flavor), and Google Cloud SQL for
Postgres, so this one adapter covers all of them; the "supported engines"
list is what routes a connection to it, not separate adapter code.
"""
from __future__ import annotations

import asyncpg

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
class PostgresAdapter(DatabaseAdapter):
    engine_key = "postgresql"
    display_name = "PostgreSQL"
    tier = 1
    default_ports = (5432, 26257)  # 26257 = CockroachDB's default, same wire protocol

    def __init__(self, params: ConnectionParams):
        super().__init__(params)
        self._conn: asyncpg.Connection | None = None

    async def _connect(self) -> asyncpg.Connection:
        if self._conn is None:
            try:
                self._conn = await asyncpg.connect(
                    host=self.params.host,
                    port=self.params.port,
                    user=self.params.username,
                    password=self.params.password,
                    database=self.params.database or "postgres",
                    ssl="require" if self.params.ssl else None,
                    timeout=self.params.connect_timeout_seconds,
                )
            except (OSError, asyncpg.PostgresError) as exc:
                raise AdapterError(f"Could not connect as PostgreSQL: {exc}") from exc
        return self._conn

    async def test_connection(self) -> dict:
        conn = await self._connect()
        version = await conn.fetchval("SHOW server_version")
        return {"version": f"PostgreSQL {version}"}

    async def discover_schemas(self) -> list[str]:
        conn = await self._connect()
        rows = await conn.fetch(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname NOT LIKE 'pg\\_%' AND nspname NOT IN ('information_schema') "
            "ORDER BY 1"
        )
        return [r["nspname"] for r in rows]

    async def discover_tables(self, schema: str | None) -> list[TableInfo]:
        conn = await self._connect()
        schemas = [schema] if schema else await self.discover_schemas()
        rows = await conn.fetch(
            "SELECT n.nspname AS schema, c.relname AS name, c.reltuples::bigint AS row_estimate "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'r' AND n.nspname = ANY($1::text[]) "
            "ORDER BY n.nspname, c.relname",
            schemas,
        )
        return [
            TableInfo(schema=r["schema"], name=r["name"], row_count_estimate=max(r["row_estimate"], 0))
            for r in rows
        ]

    async def discover_columns(self, schema: str | None, table: str) -> list[ColumnInfo]:
        conn = await self._connect()
        rows = await conn.fetch(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = $1 AND table_name = $2 ORDER BY ordinal_position",
            schema or "public",
            table,
        )
        return [ColumnInfo(name=r["column_name"], source_type=r["data_type"], nullable=r["is_nullable"] == "YES") for r in rows]

    async def _select(
        self, schema: str | None, table: str, limit: int, since_column: str | None = None, since_value: object = None
    ) -> list[dict]:
        conn = await self._connect()
        qualified = f"{quote_ident(schema or 'public')}.{quote_ident(table)}"
        if since_column and since_value is not None:
            col = quote_ident(since_column)
            rows = await conn.fetch(f"SELECT * FROM {qualified} WHERE {col} > $1 ORDER BY {col} ASC LIMIT $2", since_value, limit)
        else:
            rows = await conn.fetch(f"SELECT * FROM {qualified} LIMIT $1", limit)
        return [dict(r) for r in rows]

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
            await self._conn.close()
            self._conn = None
