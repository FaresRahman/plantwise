from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DbConnectionInput(BaseModel):
    """Either references a saved persistent connection (connection_id) or
    carries raw connection details for a one-time import — never both
    meaningfully at once; the service resolves connection_id first.
    """

    connection_id: int | None = None

    engine: str | None = None  # explicit override; None = auto-detect
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    ssl: bool = False

    # If set (and connection_id is not), persist this connection encrypted
    # under this name after a successful test — the opt-in "Persistent
    # Connection" mode. Omitted/None = one-time import, nothing stored.
    save_as: str | None = None


class TestConnectionResult(BaseModel):
    detected: list[str]
    version: str | None
    ambiguous: bool
    saved_connection_id: int | None = None


class SavedConnectionOut(BaseModel):
    """Never includes the password/ciphertext — this is the only shape a
    saved connection is ever returned to a client in.
    """

    id: int
    name: str
    engine: str
    host: str
    port: int
    database: str | None
    username: str
    ssl: bool
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class SchemaListOut(BaseModel):
    schemas: list[str]


class TableOut(BaseModel):
    schema_name: str | None
    name: str
    row_count_estimate: int | None
    recommendation_score: float
    recommendation_reason: str | None


class TableListRequest(BaseModel):
    connection: DbConnectionInput
    schema_name: str | None = None


class ColumnOut(BaseModel):
    name: str
    source_type: str
    nullable: bool


class TableDetailRequest(BaseModel):
    connection: DbConnectionInput
    schema_name: str | None = None
    table: str


class SampleRequest(TableDetailRequest):
    limit: int = 25


class TableValidateRequest(TableDetailRequest):
    # app_field -> source column name (or None/omitted if unmapped) — from
    # either /{entity}/map's suggestion or the user's override of it.
    mapping: dict[str, str | None] | None = None


class CommitRequest(BaseModel):
    edited_rows: list[dict]
    skip_invalid: bool = True


# ---------------------------------------------------------------------------
# Local Connector registration/auth (backend API surface only)
# ---------------------------------------------------------------------------

class ConnectorCreateRequest(BaseModel):
    name: str


class ConnectorRegistrationKeyOut(BaseModel):
    """registration_key is shown exactly once — the server never stores or
    returns it again after this response."""

    connector_id: int
    name: str
    registration_key: str


class ConnectorRegisterRequest(BaseModel):
    registration_key: str


class ConnectorTokenOut(BaseModel):
    """connector_token is shown exactly once — the connector app must save
    it locally; the server only ever stores its hash."""

    connector_id: int
    connector_name: str
    connector_token: str


class ConnectorOut(BaseModel):
    id: int
    name: str
    status: str
    created_at: datetime
    registered_at: datetime | None
    last_seen_at: datetime | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Connector job relay — how the dashboard asks a specific connector to do
# something (test/discover/read), and how the connector picks up that work
# and reports back. See models.py:ConnectorJob for why `params` never
# carries database credentials.
# ---------------------------------------------------------------------------

JobAction = Literal["test_connection", "discover_schemas", "discover_tables", "discover_columns", "read_rows"]


class ConnectorJobCreateRequest(BaseModel):
    action: JobAction
    # e.g. {"schema_name": "dbo", "table": "machines", "limit": 25} — only
    # ever action-specific arguments, never connection credentials.
    params: dict = {}


class ConnectorJobOut(BaseModel):
    id: int
    connector_id: int
    action: str
    params: dict
    status: str
    result: dict | list | None = None
    error: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class ConnectorJobResultRequest(BaseModel):
    status: Literal["completed", "failed"]
    result: dict | list | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Continuous sync — a saved mapping re-run on a timer. See
# app/modules/db_import/service.py:run_sync.
# ---------------------------------------------------------------------------

class SyncScheduleCreateRequest(BaseModel):
    entity: str
    connection_id: int | None = None
    connector_id: int | None = None
    schema_name: str | None = None
    table: str
    # app_field -> source column name, from the same TableValidateRequest.mapping
    # the interactive wizard's map/preview step already produced.
    column_mapping: dict[str, str] = {}
    watermark_column: str
    interval_minutes: int = 15


class SyncScheduleOut(BaseModel):
    id: int
    entity: str
    connection_id: int | None
    connector_id: int | None
    schema_name: str | None
    table_name: str
    column_mapping: dict
    watermark_column: str
    interval_minutes: int
    enabled: bool
    last_synced_at: datetime | None
    last_status: str | None
    last_error: str | None
    consecutive_failures: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SyncScheduleUpdateRequest(BaseModel):
    enabled: bool
