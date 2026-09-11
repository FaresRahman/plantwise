"""IBM Informix adapter — tier 2: reuses the same ibm_db CLI driver as Db2
(IBM's driver covers both), plus the Informix Client SDK (CSDK) native
libraries on whatever machine runs the import service. Not installed by
default (see BE/requirements.txt) — until `ibm_db` is installed, every call
raises PrerequisiteMissingError so the UI shows a clear "not ready" notice
instead of a raw connection failure.

Not verified against a live Informix instance (none available in this
environment, and the driver isn't installed here either) — built to
ibm_db's documented API and Informix's systables/syscolumns catalog.
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
    "Requires the ibm_db driver and the Informix Client SDK (CSDK) on the server. "
    "Run `pip install ibm_db`, install the CSDK, and restart the import service."
)


@register_adapter
class InformixAdapter(DatabaseAdapter):
    engine_key = "informix"
    display_name = "IBM Informix"
    tier = 2
    default_ports = (9088, 1526)
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
                f"PROTOCOL=ONSOCTCP;UID={self.params.username};PWD={self.params.password};"
            )
            try:
                self._conn = ibm_db.connect(conn_str, "", "")
            except Exception as exc:
                raise AdapterError(f"Could not connect as Informix: {exc}") from exc
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
        rows = await self._fetch("SELECT DBINFO('version', 'full') AS version FROM systables WHERE tabid = 1")
        return {"version": f"IBM Informix {rows[0]['VERSION']}" if rows else "IBM Informix"}

    async def discover_schemas(self) -> list[str]:
        rows = await self._fetch("SELECT UNIQUE owner FROM systables WHERE tabid > 99 ORDER BY 1")
        return [r["OWNER"] for r in rows if r["OWNER"]]

    async def discover_tables(self, schema: str | None) -> list[TableInfo]:
        schemas = [schema] if schema else await self.discover_schemas()
        placeholders = ",".join("?" for _ in schemas)
        rows = await self._fetch(
            f"SELECT owner, tabname, nrows FROM systables "
            f"WHERE tabtype = 'T' AND owner IN ({placeholders}) ORDER BY owner, tabname",
            tuple(schemas),
        )
        return [TableInfo(schema=r["OWNER"], name=r["TABNAME"], row_count_estimate=r["NROWS"]) for r in rows]

    async def discover_columns(self, schema: str | None, table: str) -> list[ColumnInfo]:
        rows = await self._fetch(
            "SELECT c.colname, c.coltype FROM syscolumns c JOIN systables t ON t.tabid = c.tabid "
            "WHERE t.tabname = ? AND t.owner = ? ORDER BY c.colno",
            (table, schema or self.params.username),
        )
        return [ColumnInfo(name=r["COLNAME"], source_type=str(r["COLTYPE"]), nullable=True) for r in rows]

    async def _select(self, schema: str | None, table: str, limit: int) -> list[dict]:
        qualified = f"{quote_ident(schema or self.params.username)}.{quote_ident(table)}"
        return await self._fetch(f"SELECT FIRST {int(limit)} * FROM {qualified}")

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
