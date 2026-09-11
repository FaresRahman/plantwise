from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DbConnection(Base):
    """A saved, persistent Cloud DB connection — opt-in only (PRD: "Persistent
    Connection (Optional)"). The default one-time-import mode never creates a
    row here; credentials for that mode live only in-memory for the duration
    of one request and are never written anywhere.
    """

    __tablename__ = "db_import_connections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    engine: Mapped[str] = mapped_column(String(40), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    database: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Fernet ciphertext only (app.core.credential_crypto) — never a plaintext
    # password, and no API schema in this module ever serializes this field.
    encrypted_password: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ConnectorRegistration(Base):
    """One Local Connector installation. Registration is a two-step
    exchange: an admin generates a registration_key here (shown once), the
    customer pastes it into the connector app, which calls POST
    /db-import/connectors/register to trade it for a long-lived
    connector_token (also shown once). Only SHA-256 hashes of both secrets
    are ever stored — see db_import/connector_service.py — so this table
    alone can never be used to impersonate a connector even if read.

    The customer's database credentials are never sent to or stored by the
    SaaS backend at all — the connector app keeps them in its own local,
    encrypted config file and uses them only to open its own read-only
    connection. See ConnectorJob below for how the backend asks a connector
    to do something without ever seeing those credentials.
    """

    __tablename__ = "db_import_connectors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # pending (key issued, not yet exchanged) -> active (token issued) -> revoked
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    registration_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    registered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SyncSchedule(Base):
    """A saved mapping (source table/columns -> target Plantwise entity)
    that's re-run on a timer instead of once by hand. Reuses exactly the
    same target entity/CSVSpec/commit_fn the one-off wizard commit already
    uses (see service.py:_load_entities) — the only new behavior is running
    it unattended and only pulling rows newer than the last watermark.

    Exactly one of connection_id (Cloud DB Import — the backend connects out
    directly) or connector_id (Local Connector — a read_rows ConnectorJob is
    enqueued and relayed) is set; enforced in service.py, not here, since a
    DB-level XOR constraint isn't portable and this is the only writer.
    """

    __tablename__ = "db_import_sync_schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    connection_id: Mapped[int | None] = mapped_column(ForeignKey("db_import_connections.id", ondelete="CASCADE"), nullable=True)
    connector_id: Mapped[int | None] = mapped_column(ForeignKey("db_import_connectors.id", ondelete="CASCADE"), nullable=True)

    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # {app_field: source_column, ...} — the same shape TableValidateRequest's
    # mapping already uses, just persisted instead of used once and discarded.
    column_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    watermark_column: Mapped[str] = mapped_column(String(255), nullable=False)
    # Kept as text — the watermark can be a timestamp, an integer id, etc.;
    # the adapter's parameterized query lets the driver coerce it against the
    # source column's native type rather than this table needing to know it.
    last_watermark_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ConnectorJob(Base):
    """A unit of work relayed to a specific Local Connector — how the
    dashboard asks a connector to test/discover/read something without any
    inbound connection to the customer's network. The connector initiates
    every request (polls for pending jobs, posts results back), matching
    the outbound-HTTPS-only communication requirement.

    `params` never carries database credentials — only action-specific
    arguments (schema/table/limit). The connector already knows which
    database to connect to from its own local config; the SaaS backend
    never sees the customer's credentials at any point in this flow.
    """

    __tablename__ = "db_import_connector_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    connector_id: Mapped[int] = mapped_column(ForeignKey("db_import_connectors.id", ondelete="CASCADE"), nullable=False, index=True)

    # test_connection | discover_schemas | discover_tables | discover_columns | read_rows
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # pending -> in_progress (claimed by the connector's next poll) -> completed | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
