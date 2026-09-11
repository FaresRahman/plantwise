from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    pass


async def get_db():
    async with _SessionLocal() as session:
        yield session


async def dispose_engine() -> None:
    """Gracefully dispose the async engine on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def init_db() -> None:
    """Create every table known to Base.metadata.

    Real schema evolution now happens via Alembic (`alembic/versions/`,
    applied with `alembic upgrade head` — see the Docker entrypoint, which
    runs it before the app starts). This create_all() call is kept only as
    an idempotent local-dev safety net: on a database Alembic has already
    migrated, it's a no-op (every table already matches); it should never be
    relied on as the actual migration mechanism, since it can create a
    missing table but can never ALTER an existing one. All module
    `models.py` files must be imported (see main.py) before this runs, or
    their tables won't be created/checked.
    """
    import asyncio
    import structlog

    logger = structlog.get_logger()

    global _engine, _SessionLocal

    _engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE,
    )
    _SessionLocal = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)

    from app.core.vectorstore import ensure_pgvector_extension

    retries = 5
    delay = 2
    last_err = None

    for attempt in range(1, retries + 1):
        try:
            async with _engine.begin() as conn:
                await ensure_pgvector_extension(conn)
                await conn.run_sync(Base.metadata.create_all)
            logger.info("db_ready", attempt=attempt)
            return
        except OSError as exc:
            last_err = exc
            logger.warning("db_connection_retry", attempt=attempt, retries=retries, delay=delay)
            if attempt < retries:
                await asyncio.sleep(delay)

    logger.error("db_startup_failed", retries=retries)
    raise last_err
