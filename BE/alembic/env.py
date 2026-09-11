import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.db import Base

# Import ALL models so Base.metadata knows about every table
# (append-only — add new module model imports here)
from app.core.models_shared import Tenant, AuditLog, ModuleFreshness  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.predictive_maintenance.models import (  # noqa: F401
    Asset, SensorReading, MaintenanceHistory, Recommendation, FailureCaseSignature,
)
from app.modules.production.models import Line, OutputLog  # noqa: F401
from app.modules.inventory.models import Item, StockMovement  # noqa: F401
from app.modules.quality.models import (  # noqa: F401
    Characteristic, InspectionRecord, QualityHold,
)
from app.modules.sop.models import SopDocument, SopChunk, SopQueryLog  # noqa: F401
from app.modules.shift_reports.models import ShiftSchedule, ShiftReport  # noqa: F401
from app.modules.chatbot.models import Conversation, Message  # noqa: F401
from app.modules.notifications.models import AlertSetting, SentAlert  # noqa: F401
from app.modules.onboarding.models import OnboardingProgress  # noqa: F401
from app.modules.db_import.models import (  # noqa: F401
    DbConnection, ConnectorRegistration, ConnectorJob, SyncSchedule,
)

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
