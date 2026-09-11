"""Pluggable database-engine adapters for the Database Import feature.

This is a vendored copy of BE/app/core/db_adapters/, kept standalone here
so the connector doesn't have to bundle the rest of the BE application
(FastAPI app, langchain, openai, fastembed, etc. — none of which the
connector needs) into its packaged executable. The two copies are
identical except for the import prefix (`app.core.db_adapters` ->
`db_adapters`); if you change adapter logic, change it in both places.

The import pipeline (auto field mapping -> validation -> editable preview ->
commit) never contains engine-specific logic. Each supported engine
implements the DatabaseAdapter interface in this package; adding a new
engine means adding one new adapter module + registering it — nothing else
in the import workflow changes.

See base.py for the interface, registry.py for engine registration + auto
detection.
"""
from db_adapters.base import (
    AdapterError,
    ColumnInfo,
    ConnectionParams,
    DatabaseAdapter,
    PrerequisiteMissingError,
    TableInfo,
)
from db_adapters.registry import detect_engine, get_adapter_class, list_supported_engines

# Import every adapter module so its @register_adapter decorator runs.
from db_adapters import (  # noqa: F401
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
