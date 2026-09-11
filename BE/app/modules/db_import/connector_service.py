"""Local Connector registration/auth, plus the job relay a registered
connector polls for work through (see models.py:ConnectorJob).

Deliberately not JWT-based like the rest of the app's auth (see
core/security.py) — a connector token is long-lived and must be
individually revocable the moment a customer decommissions an install,
which a stateless signed token can't do without a blocklist. Instead this
follows the API-key convention: a high-entropy random secret is generated,
handed to the caller exactly once, and only its SHA-256 hash is ever
stored — revoking is just flipping a status flag on that row.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.db_import.models import ConnectorJob, ConnectorRegistration


class ConnectorAuthError(Exception):
    """Registration-key exchange or token auth failed — router turns this
    into a 401/400, never leaking which part of the check failed."""


class ConnectorJobError(Exception):
    """Job not found / not owned by this connector — router turns this
    into a 404."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def create_connector(db: AsyncSession, tenant_id: int, user_id: int, name: str) -> tuple[ConnectorRegistration, str]:
    registration_key = secrets.token_urlsafe(32)
    connector = ConnectorRegistration(
        tenant_id=tenant_id, name=name, status="pending",
        registration_key_hash=_hash(registration_key), created_by=user_id,
    )
    db.add(connector)
    await db.commit()
    await db.refresh(connector)
    return connector, registration_key


async def exchange_registration_key(db: AsyncSession, registration_key: str) -> tuple[ConnectorRegistration, str]:
    """Public (no dashboard-user auth) — the connector app itself calls
    this once, using the key an admin generated and handed to the customer
    out-of-band. The key is single-use: exchanged for a token, then cleared.
    """
    connector = await db.scalar(
        select(ConnectorRegistration).where(
            ConnectorRegistration.registration_key_hash == _hash(registration_key),
            ConnectorRegistration.status == "pending",
        )
    )
    if connector is None:
        raise ConnectorAuthError("Invalid or already-used registration key")

    token = secrets.token_urlsafe(48)
    connector.token_hash = _hash(token)
    connector.registration_key_hash = None
    connector.status = "active"
    connector.registered_at = datetime.utcnow()
    await db.commit()
    await db.refresh(connector)
    return connector, token


async def authenticate_connector(db: AsyncSession, token: str) -> ConnectorRegistration:
    """For future connector-initiated endpoints (job polling, data relay) —
    validates the bearer token every request carries, same as get_current_user
    does for dashboard users."""
    connector = await db.scalar(
        select(ConnectorRegistration).where(
            ConnectorRegistration.token_hash == _hash(token), ConnectorRegistration.status == "active"
        )
    )
    if connector is None:
        raise ConnectorAuthError("Invalid or revoked connector token")
    connector.last_seen_at = datetime.utcnow()
    await db.commit()
    return connector


async def list_connectors(db: AsyncSession, tenant_id: int) -> list[ConnectorRegistration]:
    return list(
        await db.scalars(
            select(ConnectorRegistration).where(ConnectorRegistration.tenant_id == tenant_id).order_by(ConnectorRegistration.name)
        )
    )


async def revoke_connector(db: AsyncSession, tenant_id: int, connector_id: int) -> bool:
    connector = await db.scalar(
        select(ConnectorRegistration).where(
            ConnectorRegistration.tenant_id == tenant_id, ConnectorRegistration.id == connector_id
        )
    )
    if connector is None:
        return False
    connector.status = "revoked"
    connector.token_hash = None
    connector.revoked_at = datetime.utcnow()
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Job relay
# ---------------------------------------------------------------------------

async def create_job(db: AsyncSession, tenant_id: int, user_id: int, connector_id: int, action: str, params: dict) -> ConnectorJob:
    connector = await db.scalar(
        select(ConnectorRegistration).where(
            ConnectorRegistration.tenant_id == tenant_id, ConnectorRegistration.id == connector_id,
            ConnectorRegistration.status == "active",
        )
    )
    if connector is None:
        raise ConnectorJobError(f"Connector {connector_id} not found or not active")
    job = ConnectorJob(tenant_id=tenant_id, connector_id=connector_id, action=action, params=params, created_by=user_id)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_job(db: AsyncSession, tenant_id: int, job_id: int) -> ConnectorJob | None:
    return await db.scalar(select(ConnectorJob).where(ConnectorJob.tenant_id == tenant_id, ConnectorJob.id == job_id))


async def claim_next_job(db: AsyncSession, connector: ConnectorRegistration) -> ConnectorJob | None:
    """Called from the connector's own poll loop — atomically claims (marks
    in_progress) the oldest pending job for this connector, or returns None
    if there's nothing to do right now.
    """
    job = await db.scalar(
        select(ConnectorJob)
        .where(ConnectorJob.connector_id == connector.id, ConnectorJob.status == "pending")
        .order_by(ConnectorJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = "in_progress"
    await db.commit()
    await db.refresh(job)
    return job


async def submit_job_result(
    db: AsyncSession, connector: ConnectorRegistration, job_id: int, status: str, result: dict | list | None, error: str | None
) -> ConnectorJob:
    job = await db.scalar(
        select(ConnectorJob).where(ConnectorJob.connector_id == connector.id, ConnectorJob.id == job_id)
    )
    if job is None:
        raise ConnectorJobError(f"Job {job_id} not found for this connector")
    job.status = status
    job.result = result
    job.error = error
    job.completed_at = datetime.utcnow()
    await db.commit()

    # A job enqueued by run_sync's connector branch carries this tag — route
    # its result through the same validate/commit pipeline an interactive
    # wizard commit uses, instead of just sitting there as raw preview data
    # (which is all a plain interactive read_rows job ever needed).
    #
    # Isolated in its own try/except: the job's own completion above is
    # already committed by this point, so a bug in sync processing must not
    # surface as a 500 to the connector (which has no useful retry response
    # to that — the underlying job is already done). handle_sync_job_result
    # already records its own failure state for genuine sync errors; this
    # only guards against something unexpected escaping that.
    sync_schedule_id = (job.params or {}).get("sync_schedule_id")
    if sync_schedule_id is not None:
        from app.modules.db_import import service as db_import_service

        try:
            await db_import_service.handle_sync_job_result(db, sync_schedule_id, status, result, error)
        except Exception:
            pass

    return job
