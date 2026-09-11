"""IBM Db2 adapter — tier 2: requires the ibm_db driver, which needs IBM's
native Data Server client libraries on whatever machine runs the import
service. Not installed by default (see BE/requirements.txt) — install with
`pip install ibm_db` and this adapter activates automatically; until then
every call raises PrerequisiteMissingError so the UI shows a clear
"not ready" notice instead of a raw connection failure.

Not verified against a live Db2 instance (none available in this
environment, and the driver isn't installed here either) — built to
ibm_db's documented API and Db2's SYSCAT views.
"""
from __future__ import annotations

import asyncio

from db_adapters.base import (
    AdapterError,
    ColumnInfo,
    ConnectionParams,
    DatabaseAdapter,
    PrerequisiteMissingError,
    TableInfo,
    quote_ident,
)
from db_adapters.registry import register_adapter

MAX_IMPORT_ROWS = 50_000
_PREREQUISITE_NOTE = (
    "Requires the ibm_db driver and IBM Data Server native client libraries on the server. "
    "Run `pip install ibm_db` and restart the import service."
)


@register_adapter
class Db2Adapter(DatabaseAdapter):
    engine_key = "db2"
    display_name = "IBM Db2"
    tier = 2
    default_ports = (50000, 50001)
    prerequisite_note = _PREREQUISITE_NOTE

    def __init__(self, params: ConnectionParams):
        super().__init__(params)
        self._conn = None

    @staticmethod
    def _driver():
        try:
            import ibm_db
        except ImportError as exc:
            raise PrerequisiteMissingError(_PREREQUISITE_NOTE) from exc
        return ibm_db

    def _sync_connect(self):
        ibm_db = self._driver()
        if self._conn is None:
            conn_str = (
                f"DATABASE={self.params.database};HOSTNAME={self.params.host};PORT={self.params.port};"
                f"PROTOCOL=TCPIP;UID={self.params.username};PWD={self.params.password};"
            )
            try:
                self._conn = ibm_db.connect(conn_str, "", "")
            except Exception as exc:
                raise AdapterError(f"Could not connect as Db2: {exc}") from exc
        return self._conn

    def _sync_fetch(self, sql: str, args: tuple = ()) -> list[dict]:
        ibm_db = self._driver()
        conn = self._sync_connect()
        stmt = ibm_db.prepare(conn, sql) if args else ibm_db.exec_immediate(conn, sql)
        if args:
            ibm_db.execute(stmt, args)
        rows = []
        row = ibm_db.fetch_assoc(stmt)
        while row:
            rows.append(row)
            row = ibm_db.fetch_assoc(stmt)
        return rows

    async def _fetch(self, sql: str, args: tuple = ()) -> list[dict]:
        return await asyncio.to_thread(self._sync_fetch, sql, args)

    async def test_connection(self) -> dict:
        rows = await self._fetch("SELECT service_level AS version FROM sysibmadm.env_inst_info")
        return {"version": f"IBM Db2 {rows[0]['VERSION']}" if rows else "IBM Db2"}

    async def discover_schemas(self) -> list[str]:
        rows = await self._fetch("SELECT schemaname FROM syscat.schemata WHERE schemaname NOT LIKE 'SYS%' ORDER BY 1")
        return [r["SCHEMANAME"] for r in rows]

    async def discover_tables(self, schema: str | None) -> list[TableInfo]:
        schemas = [schema] if schema else await self.discover_schemas()
        placeholders = ",".join("?" for _ in schemas)
        rows = await self._fetch(
            f"SELECT tabschema, tabname, card FROM syscat.tables "
            f"WHERE type = 'T' AND tabschema IN ({placeholders}) ORDER BY tabschema, tabname",
            tuple(schemas),
        )
        return [TableInfo(schema=r["TABSCHEMA"], name=r["TABNAME"], row_count_estimate=r["CARD"]) for r in rows]

    async def discover_columns(self, schema: str | None, table: str) -> list[ColumnInfo]:
        rows = await self._fetch(
            "SELECT colname, typename, nulls FROM syscat.columns WHERE tabschema = ? AND tabname = ? ORDER BY colno",
            (schema or self.params.username.upper(), table.upper()),
        )
        return [ColumnInfo(name=r["COLNAME"], source_type=r["TYPENAME"], nullable=r["NULLS"] == "Y") for r in rows]

    async def _select(self, schema: str | None, table: str, limit: int) -> list[dict]:
        qualified = f"{quote_ident(schema or self.params.username.upper())}.{quote_ident(table.upper())}"
        return await self._fetch(f"SELECT * FROM {qualified} FETCH FIRST {int(limit)} ROWS ONLY")

    async def sample_rows(self, schema: str | None, table: str, limit: int = 25) -> list[dict]:
        return await self._select(schema, table, limit)

    async def read_rows(self, schema: str | None, table: str, limit: int | None = None) -> list[dict]:
        return await self._select(schema, table, min(limit, MAX_IMPORT_ROWS) if limit else MAX_IMPORT_ROWS)

    async def close(self) -> None:
        if self._conn is not None:
            try:
                ibm_db = self._driver()
                await asyncio.to_thread(ibm_db.close, self._conn)
            except PrerequisiteMissingError:
                pass
            self._conn = None
