"""Thin HTTP client for the connector's calls to the SaaS backend. Every
call here is outbound (the connector initiates all communication) — no
inbound port is ever opened, matching the "connector-initiated,
outbound-HTTPS-only" communication requirement.
"""
from __future__ import annotations

import datetime
import decimal
import json

import httpx


class ApiClientError(Exception):
    pass


def _json_default(obj):
    """read_rows results (used by continuous sync) commonly carry real
    datetime/date/Decimal values straight from the driver — httpx's default
    JSON encoder can't serialize those and would raise TypeError, silently
    failing every sync job against a table with a timestamp or numeric
    column (i.e. almost every sensor-reading or maintenance-history table).
    ISO format specifically (not str()'s space-separated default) so the
    backend's own watermark parsing (datetime.fromisoformat) round-trips it.
    """
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    return str(obj)


async def register(backend_url: str, registration_key: str) -> dict:
    """Exchange a one-time registration key for a long-lived connector
    token. Returns {"connector_id", "connector_name", "connector_token"} —
    the caller must persist the token (encrypted); the backend never
    returns it again after this call.
    """
    try:
        async with httpx.AsyncClient(base_url=backend_url, timeout=15.0) as client:
            resp = await client.post("/db-import/connectors/register", json={"registration_key": registration_key})
    except httpx.RequestError as exc:
        # Network-level failure (unreachable host, DNS, timeout) — distinct
        # from an HTTP error response, and would otherwise surface as an
        # unhandled 500 on this local page instead of a readable message.
        raise ApiClientError(f"Could not reach {backend_url}: {exc}") from exc
    if resp.status_code != 200:
        raise ApiClientError(_error_detail(resp))
    return resp.json()


async def poll_next_job(backend_url: str, token: str) -> dict | None:
    try:
        async with httpx.AsyncClient(base_url=backend_url, timeout=15.0) as client:
            resp = await client.get("/db-import/connector/jobs/next", headers=_auth(token))
    except httpx.RequestError as exc:
        raise ApiClientError(f"Could not reach {backend_url}: {exc}") from exc
    if resp.status_code == 200:
        return resp.json()  # None if the backend had no pending job
    if resp.status_code == 401:
        raise ApiClientError("Connector token was rejected. It may have been revoked, re-register this connector.")
    raise ApiClientError(_error_detail(resp))


async def submit_job_result(backend_url: str, token: str, job_id: int, status: str, result, error: str | None) -> None:
    body = json.dumps({"status": status, "result": result, "error": error}, default=_json_default).encode("utf-8")
    try:
        async with httpx.AsyncClient(base_url=backend_url, timeout=30.0) as client:
            resp = await client.post(
                f"/db-import/connector/jobs/{job_id}/result",
                headers={**_auth(token), "Content-Type": "application/json"},
                content=body,
            )
    except httpx.RequestError as exc:
        raise ApiClientError(f"Could not reach {backend_url}: {exc}") from exc
    if resp.status_code != 200:
        raise ApiClientError(_error_detail(resp))


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _error_detail(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail")
        return str(detail) if detail else f"HTTP {resp.status_code}"
    except Exception:
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
