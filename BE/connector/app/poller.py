"""Background loop: polls the SaaS backend for pending jobs, executes each
one locally against the configured database (via the vendored db_adapters
package — the same adapters Cloud DB Import uses server-side), and posts
the result back. The connector always initiates the HTTP calls; the SaaS
backend never opens a connection to the connector.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app import api_client
from app.config import ConnectorConfig, load_config
from db_adapters import ConnectionParams, get_adapter_class
from db_adapters.registry import detect_engine

logger = logging.getLogger("connector.poller")


def _parse_since_value(value):
    """since_value arrives over JSON as plain text (or null) — recover the
    likely native type before handing it to the adapter, same reasoning as
    the backend's own db_import/service.py:_parse_watermark: a bare string
    compared against a timestamp/integer column can mismatch types.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        pass
    return value


async def execute_job(config: ConnectorConfig, action: str, params: dict):
    if config.db_connection is None:
        raise RuntimeError("No database connection is configured on this connector yet — set one up in the connector's local UI first.")

    dbc = config.db_connection
    conn_params = ConnectionParams(
        host=dbc.host, port=dbc.port, username=dbc.username, password=config.db_password or "",
        database=dbc.database, ssl=dbc.ssl, engine=dbc.engine,
    )

    if not conn_params.engine:
        # include_local_only=True: unlike Cloud DB Import (which always
        # reaches over the network), the connector runs on the same machine
        # the database might be on, so file-based engines like SQLite are a
        # legitimate target here.
        detection = await detect_engine(conn_params, include_local_only=True)
        if not detection["detected"]:
            raise RuntimeError("Could not detect the configured database's engine — check host/port/credentials.")
        conn_params.engine = detection["detected"][0]

    adapter = get_adapter_class(conn_params.engine)(conn_params)
    try:
        if action == "test_connection":
            return await adapter.test_connection()
        if action == "discover_schemas":
            return {"schemas": await adapter.discover_schemas()}
        if action == "discover_tables":
            tables = await adapter.discover_tables(params.get("schema_name"))
            return [{"schema_name": t.schema, "name": t.name, "row_count_estimate": t.row_count_estimate} for t in tables]
        if action == "discover_columns":
            if "table" not in params:
                raise RuntimeError("discover_columns requires 'table' in params")
            cols = await adapter.discover_columns(params.get("schema_name"), params["table"])
            return [{"name": c.name, "source_type": c.source_type, "nullable": c.nullable} for c in cols]
        if action == "read_rows":
            if "table" not in params:
                raise RuntimeError("read_rows requires 'table' in params")
            # since_column/since_value (both optional) are how the backend's
            # continuous-sync scheduler asks for only rows newer than the
            # last watermark instead of a full re-pull every tick.
            return await adapter.read_rows(
                params.get("schema_name"), params["table"], params.get("limit"),
                since_column=params.get("since_column"), since_value=_parse_since_value(params.get("since_value")),
            )
        raise RuntimeError(f"Unknown job action '{action}'")
    finally:
        await adapter.close()


async def poll_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        config = load_config()
        if not config.is_registered:
            await _wait(stop_event, config.poll_interval_seconds)
            continue

        try:
            job = await api_client.poll_next_job(config.backend_url, config.token)
        except api_client.ApiClientError as exc:
            logger.warning("poll failed: %s", exc)
            await _wait(stop_event, config.poll_interval_seconds)
            continue

        if job is None:
            await _wait(stop_event, config.poll_interval_seconds)
            continue

        logger.info("running job %s (%s)", job["id"], job["action"])
        try:
            result = await execute_job(config, job["action"], job["params"])
            await api_client.submit_job_result(config.backend_url, config.token, job["id"], "completed", result, None)
            logger.info("job %s completed", job["id"])
        except Exception as exc:
            logger.exception("job %s failed", job["id"])
            try:
                await api_client.submit_job_result(config.backend_url, config.token, job["id"], "failed", None, str(exc))
            except api_client.ApiClientError:
                logger.exception("could not report job %s's failure back to the backend", job["id"])


async def _wait(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
