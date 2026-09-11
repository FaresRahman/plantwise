import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from structlog import get_logger

from app.core import module_registry
from app.core.config import settings
from app.core.db import dispose_engine, init_db
from app.core.llm import get_embeddings
from app.core.rate_limit import limiter
from app.core.scheduler import start_scheduler, stop_scheduler
from app.core.logging import configure_logging

# Import every module package once so its router.py runs register_module() at
# import time. This is the one shared, append-only line each new module adds
# — keep additions here to a single line per module to keep merges trivial.
from app.modules.auth import router as _auth_router  # noqa: F401
from app.modules.predictive_maintenance import router as _pm_router  # noqa: F401
from app.modules.production import router as _production_router  # noqa: F401
from app.modules.inventory import router as _inventory_router  # noqa: F401
from app.modules.quality import router as _quality_router  # noqa: F401
from app.modules.notifications import router as _notifications_router  # noqa: F401
from app.modules.sop import router as _sop_router  # noqa: F401
from app.modules.chatbot import router as _chatbot_router  # noqa: F401
from app.modules.shift_reports import router as _shift_reports_router  # noqa: F401
from app.modules.dashboard import router as _dashboard_router  # noqa: F401
from app.modules.onboarding import router as _onboarding_router  # noqa: F401
from app.modules.admin import router as _admin_router  # noqa: F401
from app.modules.db_import import router as _db_import_router  # noqa: F401

configure_logging()
logger = get_logger()

# Rate limiter — in-process, per-worker. Redis-backed in follow-up if needed.
# (instance itself lives in app/core/rate_limit.py so module routers can
# apply their own tighter per-endpoint limits without a circular import)
app = FastAPI(title="Plantwise API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    """Catch-all: log the full error but return a sanitised 500 to the
    client so no internal tracebacks leak."""
    logger.error("unhandled_exception", path=request.url.path, method=request.method, exc_info=exc)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# Trusted host enforcement in production
if settings.ALLOWED_HOSTS:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[h.strip() for h in settings.ALLOWED_HOSTS.split(",") if h.strip()],
    )

# In development, allow all origins (dev runs on random ports/IPs).
# In production, use the explicit CORS_ORIGINS list from config.
if settings.ENV == "development":
    cors_origins = ["*"]
    cors_credentials = False
else:
    cors_origins = settings.CORS_ORIGINS
    cors_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a unique request-id to every request for tracing."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


for registration in module_registry.MODULES:
    app.include_router(registration.router, prefix=f"/api/v1/{registration.prefix}", tags=[registration.key])


@app.on_event("startup")
async def on_startup() -> None:
    try:
        logger.info("starting_up")
        await init_db()
        # Loads (and, first run only, downloads) the open-source embedding model
        # once at boot — see core/llm.py — so the cost lands here, not on
        # whichever request happens to trigger the first SOP embed/query.
        get_embeddings()
        start_scheduler()
        logger.info("startup_complete")
    except Exception:
        logger.exception("startup_failed")
        raise


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("shutting_down")
    stop_scheduler()
    await dispose_engine()
    logger.info("shutdown_complete")


@app.get("/health")
@limiter.exempt
async def health():
    from sqlalchemy import text
    from app.core.db import _engine as db_engine
    from app.core.llm import _embedding_model as emb_model

    checks: dict = {"status": "ok"}

    # Database connectivity
    if db_engine is not None:
        try:
            async with db_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "unreachable"
            checks["status"] = "degraded"
    else:
        checks["database"] = "not_initialised"
        checks["status"] = "degraded"

    # Embedding model
    if emb_model is not None:
        checks["embeddings"] = "loaded"
    else:
        checks["embeddings"] = "not_loaded"
        checks["status"] = "degraded"

    return checks
