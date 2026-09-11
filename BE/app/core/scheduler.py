"""Background scheduler that auto-generates shift reports when a shift
schedule's end time is reached.  Runs a lightweight asyncio loop every 5
minutes and is started / stopped by main.py's startup / shutdown events.
"""
import asyncio
from datetime import datetime, timezone

import structlog

from app.core import db as db_module

logger = structlog.get_logger()

_scheduler_task = None


async def _check_and_generate():
    from app.modules.shift_reports import service as sr_service
    from app.modules.shift_reports.models import ShiftSchedule
    from sqlalchemy import select

    async with db_module._SessionLocal() as db:
        schedules = (await db.execute(select(ShiftSchedule))).scalars().all()
        # Everything below (the fire-check AND the window a generated report
        # covers) is computed from this single `now` — previously the window
        # was separately recomputed from naive server-local `date.today()`
        # inside _resolve_window, which could land on a different calendar
        # day than this UTC check near midnight or on a non-UTC host.
        now = datetime.now(timezone.utc)
        today = now.date()

        for schedule in schedules:
            end_minutes = schedule.end_time.hour * 60 + schedule.end_time.minute
            now_minutes = now.hour * 60 + now.minute
            if 0 <= (now_minutes - end_minutes) < 5 and schedule.last_generated_date != today:
                # Persisted dedup state (was an in-memory dict — lost on
                # restart and not shared across multiple app instances, so a
                # redeploy or horizontal scale-out could double-generate/
                # double-email a report at shift end). Committed before the
                # generate/send call so a concurrent instance's read of this
                # row reflects the claim as early as possible.
                schedule.last_generated_date = today
                await db.commit()
                try:
                    await sr_service.generate_report(
                        db,
                        schedule.tenant_id,
                        shift_schedule_id=schedule.id,
                        window_start=None,
                        window_end=None,
                        now=now,
                    )
                except Exception:
                    # Pre-existing gap, fixed alongside the same issue found in
                    # the sync/PM jobs below: this session is shared across
                    # every shift schedule in this tick, so a DB-level failure
                    # generating one report must be rolled back or it silently
                    # breaks every schedule processed after it too.
                    await db.rollback()


async def _run_due_syncs():
    """Continuous DB sync — re-runs any enabled SyncSchedule whose interval
    has elapsed. A customer who never sets one of these up (no linked DB)
    is entirely unaffected: due_sync_schedules() simply returns nothing for
    them, and they keep using manual entry / CSV upload as before.
    """
    from app.modules.db_import import service as db_import_service

    async with db_module._SessionLocal() as db:
        for schedule in await db_import_service.due_sync_schedules(db):
            try:
                await db_import_service.run_sync(db, schedule)
            except Exception:
                # run_sync/​_mark_sync_failure already roll back on a DB-level
                # failure, but this is a defensive backstop: this session is
                # shared across every due schedule in this tick, so an
                # unrolled-back aborted transaction here would silently break
                # every schedule processed after this one too.
                await db.rollback()


async def _run_predictive_maintenance_recompute():
    """Runs the predictive-maintenance rule/pattern engine for every tenant
    on a schedule, not only when new data happens to be uploaded — this is
    what lets a historical-pattern match (or a threshold/trend breach) fire
    and email an alert even if nobody opens the app that day.
    """
    from sqlalchemy import select

    from app.core.models_shared import Tenant
    from app.modules.predictive_maintenance.engine import recompute_all

    async with db_module._SessionLocal() as db:
        tenant_ids = (await db.execute(select(Tenant.id))).scalars().all()
        for tenant_id in tenant_ids:
            try:
                await recompute_all(db, tenant_id)
            except Exception:
                # Same reasoning as _run_due_syncs: this session is shared
                # across every tenant in this tick, so a DB-level failure for
                # one tenant must be rolled back or it silently breaks every
                # tenant recomputed after it too.
                await db.rollback()


async def _scheduler_loop(interval_seconds: int = 60):
    """60s, not the 5-minute cadence any individual sync/recompute actually
    needs — this only controls how often the scheduler checks for due work,
    not how often a database actually gets synced (that's the separate,
    per-schedule interval_minutes floor, enforced at creation time). A
    faster tick just means a due sync or a fresh recommendation is noticed
    within a minute instead of sitting unrecognized for up to 5 — worth it
    at negligible cost in both dev and production, so one constant serves
    both rather than branching by environment.

    Each tick's three jobs already guard their own per-item work (a bad
    row/tenant/schedule can't break the others in the same tick) — but
    nothing previously guarded the tick itself. Any exception raised outside
    those inner try/excepts (e.g. the schedule/tenant lookup query, or even
    just opening the session) would propagate out of this `while True` and
    kill the background task for good, silently — no log, no restart, and
    every future sync/recompute/shift-report tick simply never happens
    again until the process is restarted. That is exactly what continuous
    DB sync (the app's core promise: connect once, stay current forever)
    cannot tolerate, so every tick's three jobs now run independently and
    any failure is logged and the loop continues to its next tick either way.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        for job in (_check_and_generate, _run_due_syncs, _run_predictive_maintenance_recompute):
            try:
                await job()
            except Exception:
                logger.exception("scheduler_tick_job_failed", job=job.__name__)


def start_scheduler():
    global _scheduler_task
    if _scheduler_task is None:
        _scheduler_task = asyncio.create_task(_scheduler_loop())


def stop_scheduler():
    global _scheduler_task
    if _scheduler_task is not None:
        _scheduler_task.cancel()
        _scheduler_task = None
