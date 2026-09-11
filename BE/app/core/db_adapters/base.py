"""Common interface every database-engine adapter implements. Nothing in
app.modules.db_import (the router/service that drives Database Import) ever
imports a specific driver directly — it only talks to this interface, so
adding a new engine never touches the import workflow.

Every adapter is strictly read-only: the only operations any adapter may
issue against the customer's database are a handful of metadata-catalog
queries and SELECT ... LIMIT n. No adapter method exists for INSERT/UPDATE/
DELETE/DDL, and none should ever be added.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ConnectionParams:
    host: str
    port: int
    username: str
    password: str
    database: str | None = None
    ssl: bool = False
    # Explicit engine override (engine_key, e.g. "postgresql") — when unset,
    # app.core.db_adapters.registry.detect_engine() figures it out.
    engine: str | None = None
    connect_timeout_seconds: float = 6.0


@dataclass
class ColumnInfo:
    name: str
    # Raw source-side type name (e.g. "varchar", "integer", "timestamp") —
    # shown to the user during table/column browsing. The import pipeline's
    # own dtype coercion (str/int/float/datetime/enum) is driven by the
    # *target* app field spec, not this — see core.ingestion.ColumnSpec.
    source_type: str
    nullable: bool = True


@dataclass
class TableInfo:
    schema: str | None
    name: str
    row_count_estimate: int | None = None
    columns: list[ColumnInfo] = field(default_factory=list)
    # Filled in by the "intelligent table detection" recommender
    # (app.modules.db_import.service.recommend_tables), not by the adapter
    # itself — an adapter just reports what exists.
    recommendation_score: float = 0.0
    recommendation_reason: str | None = None


class AdapterError(Exception):
    """Connection/query failure — the message is safe to show a user
    verbatim (adapters must never interpolate the password into it).
    """


class PrerequisiteMissingError(AdapterError):
    """Raised by a tier-2 adapter when its driver's native client library
    isn't installed/reachable — message must name what's missing and how to
    install it, so the frontend can surface it as an actionable prerequisite
    notice rather than a generic connection failure.
    """


def quote_ident(name: str, quote_char: str = '"') -> str:
    """Safely quote a schema/table/column identifier for interpolation into
    a SQL string. Identifiers can't be bound as query parameters the way
    values can, so every adapter needs this — but every identifier this is
    ever called with comes from the engine's own metadata catalog (what
    discover_schemas/discover_tables/discover_columns reported exists), not
    from raw user input, and doubling the quote character neutralizes an
    embedded quote either way.
    """
    escaped = name.replace(quote_char, quote_char * 2)
    return f"{quote_char}{escaped}{quote_char}"


EngineTier = Literal[1, 2]


class DatabaseAdapter:
    """Base class for one engine's adapter. Subclasses set the class
    attributes and implement every method below. All methods are read-only:
    metadata discovery + SELECT ... LIMIT n only.
    """

    engine_key: str = ""
    display_name: str = ""
    tier: EngineTier = 1
    default_ports: tuple[int, ...] = ()
    # Shown in the UI before the user attempts to connect, for tier-2
    # engines whose driver needs something beyond `pip install` (e.g. a
    # native client library) — None for tier-1 engines.
    prerequisite_note: str | None = None
    # File-based engines (SQLite) have no host/port to reach over the
    # network — they're only ever usable through the Local Connector, which
    # runs on the same machine as the file. Cloud Database Import excludes
    # any adapter with local_only=True from its engine picker/detection.
    local_only: bool = False

    def __init__(self, params: ConnectionParams):
        self.params = params

    async def test_connection(self) -> dict:
        """Connect, run a trivial query, return {"version": "..."}. Raises
        AdapterError (or PrerequisiteMissingError for a tier-2 adapter
        missing its native driver) on failure — never returns False/None.
        """
        raise NotImplementedError

    async def discover_schemas(self) -> list[str]:
        raise NotImplementedError

    async def discover_tables(self, schema: str | None) -> list[TableInfo]:
        """List tables (with a fast row-count estimate, not COUNT(*)) in the
        given schema, or every user schema if schema is None.
        """
        raise NotImplementedError

    async def discover_columns(self, schema: str | None, table: str) -> list[ColumnInfo]:
        raise NotImplementedError

    async def sample_rows(self, schema: str | None, table: str, limit: int = 25) -> list[dict]:
        """A small preview of raw rows (dict of column name -> value), for
        display before the user commits to importing this table.
        """
        raise NotImplementedError

    async def read_rows(
        self,
        schema: str | None,
        table: str,
        limit: int | None = None,
        since_column: str | None = None,
        since_value: object | None = None,
    ) -> list[dict]:
        """The full (or capped) row set that actually gets fed into
        auto_map_columns/validate_records for import.

        since_column/since_value (both optional, both-or-neither) add a
        WHERE {since_column} > {since_value} ORDER BY {since_column} filter —
        continuous sync's incremental pull, so each tick only fetches rows
        newer than the last watermark instead of the whole table. since_value
        is passed as a native Python value (int/datetime/str, whatever the
        caller parsed the stored watermark into), not always a string — the
        underlying driver needs to infer the right wire type from the value
        itself to compare correctly against a non-text column.
        """
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def __aenter__(self) -> "DatabaseAdapter":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()
