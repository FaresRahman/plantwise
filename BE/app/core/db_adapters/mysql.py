"""MySQL adapter — MariaDB and the MySQL-flavored managed clouds (Amazon
Aurora MySQL, Google Cloud SQL for MySQL) are wire-compatible, so this one
adapter covers all of them.
"""
from __future__ import annotations

import ssl as ssl_module

import aiomysql

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
_SYSTEM_SCHEMAS = ("information_schema", "mysql", "performance_schema", "sys")


@register_adapter
class MySQLAdapter(DatabaseAdapter):
    engine_key = "mysql"
    display_name = "MySQL / MariaDB"
    tier = 1
    default_ports = (3306,)

    def __init__(self, params: ConnectionParams):
        super().__init__(params)
        self._conn: aiomysql.Connection | None = None

    async def _connect(self) -> aiomysql.Connection:
        if self._conn is None:
            try:
                self._conn = await aiomysql.connect(
                    host=self.params.host,
                    port=self.params.port,
                    user=self.params.username,
                    password=self.params.password,
                    db=self.params.database,
                    ssl=ssl_module.create_default_context() if self.params.ssl else None,
                    connect_timeout=self.params.connect_timeout_seconds,
                )
            except (OSError, aiomysql.Error) as exc:
                raise AdapterError(f"Could not connect as MySQL/MariaDB: {exc}") from exc
        return self._conn

    async def _fetch(self, sql: str, args: tuple = ()) -> list[dict]:
        conn = await self._connect()
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, args)
            return list(await cur.fetchall())

    async def test_connection(self) -> dict:
        rows = await self._fetch("SELECT VERSION() AS version")
        return {"version": f"MySQL/MariaDB {rows[0]['version']}"}

    async def discover_schemas(self) -> list[str]:
        placeholders = ",".join(["%s"] * len(_SYSTEM_SCHEMAS))
        rows = await self._fetch(
            f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
            f"WHERE SCHEMA_NAME NOT IN ({placeholders}) ORDER BY 1",
            _SYSTEM_SCHEMAS,
        )
        return [r["SCHEMA_NAME"] for r in rows]

    async def discover_tables(self, schema: str | None) -> list[TableInfo]:
        schemas = [schema] if schema else await self.discover_schemas()
        placeholders = ",".join(["%s"] * len(schemas))
        rows = await self._fetch(
            f"SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES "
            f"WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA IN ({placeholders}) "
            f"ORDER BY TABLE_SCHEMA, TABLE_NAME",
            schemas,
        )
        return [
            TableInfo(schema=r["TABLE_SCHEMA"], name=r["TABLE_NAME"], row_count_estimate=r["TABLE_ROWS"])
            for r in rows
        ]

    async def discover_columns(self, schema: str | None, table: str) -> list[ColumnInfo]:
        rows = await self._fetch(
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
            (schema or self.params.database, table),
        )
        return [ColumnInfo(name=r["COLUMN_NAME"], source_type=r["DATA_TYPE"], nullable=r["IS_NULLABLE"] == "YES") for r in rows]

    async def _select(
        self, schema: str | None, table: str, limit: int, since_column: str | None = None, since_value: object = None
    ) -> list[dict]:
        qualified = f"{quote_ident(schema or self.params.database, '`')}.{quote_ident(table, '`')}"
        if since_column and since_value is not None:
            col = quote_ident(since_column, '`')
            return await self._fetch(f"SELECT * FROM {qualified} WHERE {col} > %s ORDER BY {col} ASC LIMIT %s", (since_value, limit))
        return await self._fetch(f"SELECT * FROM {qualified} LIMIT %s", (limit,))

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
            self._conn.close()
            self._conn = None
