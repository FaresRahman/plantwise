"""Pluggable database-engine adapters for the Database Import feature.

The import pipeline (auto field mapping -> validation -> editable preview ->
commit, see app.core.ingestion) never contains engine-specific logic. Each
supported engine implements the DatabaseAdapter interface in this package;
adding a new engine means adding one new adapter module + registering it —
nothing else in the import workflow changes.

See base.py for the interface, registry.py for engine registration + auto
detection.
"""
from app.core.db_adapters.base import (
    AdapterError,
    ColumnInfo,
    ConnectionParams,
    DatabaseAdapter,
    PrerequisiteMissingError,
    TableInfo,
)
from app.core.db_adapters.registry import detect_engine, get_adapter_class, list_supported_engines

# Import every adapter module so its @register_adapter decorator runs.
from app.core.db_adapters import (  # noqa: F401
    db2,
    firebird,
    hana,
    informix,
    mssql,
    mysql,
    oracle,
    postgres,
    sqlite,
)

__all__ = [
    "AdapterError",
    "ColumnInfo",
    "ConnectionParams",
    "DatabaseAdapter",
    "PrerequisiteMissingError",
    "TableInfo",
    "detect_engine",
    "get_adapter_class",
    "list_supported_engines",
]
