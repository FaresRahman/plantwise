"""Shared test fixtures and utilities for PlantWise backend tests."""

import os

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_db():
    """Returns an AsyncMock that mimics an async SQLAlchemy session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.scalars = AsyncMock()
    return session


@pytest.fixture
def tenant_id() -> int:
    return 1


@pytest.fixture
def user_id() -> int:
    return 42


# ---------------------------------------------------------------------------
# Real-database fixtures for @pytest.mark.integration tests.
#
# These exercise the actual engine/service functions (production OEE,
# quality defect-trend/drift, inventory run-out, alert dedup, ...) against a
# real Postgres instance — the `mock_db` fixture above is fine for API
# contract tests, but a fully-mocked session can't catch a wrong SQL
# WHERE-clause or a real arithmetic bug, only whether a function was called.
#
# Requires `docker compose up -d postgres` (see BE/docker-compose.yml) to be
# running first. Skips (doesn't fail) if that database isn't reachable, so
# `pytest` still passes cleanly for anyone who hasn't started it — but CI
# should provision Postgres and run these for real coverage.
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://plantwise:plantwise@localhost:5433/plantwise_test"
)


def _import_all_models() -> None:
    """Same import list as alembic/env.py — must run before
    Base.metadata.create_all() or a module's table(s) won't exist."""
    import app.core.models_shared  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.predictive_maintenance.models  # noqa: F401
    import app.modules.production.models  # noqa: F401
    import app.modules.inventory.models  # noqa: F401
    import app.modules.quality.models  # noqa: F401
    import app.modules.sop.models  # noqa: F401
    import app.modules.shift_reports.models  # noqa: F401
    import app.modules.chatbot.models  # noqa: F401
    import app.modules.notifications.models  # noqa: F401
    import app.modules.onboarding.models  # noqa: F401
    import app.modules.db_import.models  # noqa: F401


@pytest_asyncio.fixture
async def db():
    """A real AsyncSession against a dedicated `plantwise_test` database,
    schema created fresh via Base.metadata.create_all() and all tables
    truncated before the test runs (so every test starts from an empty,
    known state regardless of execution order). The engine is created fresh
    per test (not session-scoped) to sidestep asyncpg connections being
    bound to whatever event loop created them, which pytest-asyncio's
    per-test loop would otherwise break.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.db import Base
    from app.core.vectorstore import ensure_pgvector_extension

    _import_all_models()

    # A short connect timeout so a stopped/unreachable Postgres fails fast
    # into the skip path below, instead of every test in the file stalling
    # on the driver's default connect timeout one-by-one.
    engine = create_async_engine(TEST_DATABASE_URL, connect_args={"timeout": 3})
    try:
        async with engine.begin() as conn:
            await ensure_pgvector_extension(conn)
            await conn.run_sync(Base.metadata.create_all)
            table_names = ",".join(t.name for t in Base.metadata.sorted_tables)
            if table_names:
                await conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    except OSError:
        await engine.dispose()
        pytest.skip(
            f"Postgres not reachable at {TEST_DATABASE_URL} — run `docker compose up -d postgres` "
            "(from BE/) and `CREATE DATABASE plantwise_test;` to enable integration tests."
        )
        return

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()
