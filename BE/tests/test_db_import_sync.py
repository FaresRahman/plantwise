"""Integration tests for continuous DB sync (app/modules/db_import) — run
against a real Postgres database, same conventions as test_engines_integration.py.

Requires `docker compose up -d postgres` (from BE/) and a `plantwise_test`
database — see tests/conftest.py's `db` fixture, which skips gracefully (not
a failure) if that's not running.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.core.credential_crypto import encrypt_credential
from app.core.models_shared import Tenant
from app.modules.db_import.models import ConnectorRegistration, DbConnection, SyncSchedule

pytestmark = pytest.mark.integration


async def _make_tenant(db, name="Sync Test Plant") -> Tenant:
    tenant = Tenant(name=name)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def _make_connection(db, tenant_id, **overrides) -> DbConnection:
    defaults = dict(
        tenant_id=tenant_id, name="Test Conn", engine="postgresql",
        host="localhost", port=5433, database="plantwise_test", username="plantwise",
        encrypted_password=encrypt_credential("plantwise"), created_by=1,
    )
    defaults.update(overrides)
    conn = DbConnection(**defaults)
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn


class TestSyncScheduleTenantIsolation:
    """Regression coverage for a real cross-tenant bug found on review:
    create_sync_schedule originally never verified a connection_id/
    connector_id actually belonged to the calling tenant.
    """

    async def test_rejects_another_tenants_connection_id(self, db):
        from app.modules.db_import.service import SyncError, create_sync_schedule

        owner_tenant = await _make_tenant(db, "Owner")
        attacker_tenant = await _make_tenant(db, "Attacker")
        conn = await _make_connection(db, owner_tenant.id)

        with pytest.raises(SyncError):
            await create_sync_schedule(
                db, attacker_tenant.id, user_id=1, entity="sensor_readings",
                connection_id=conn.id, connector_id=None, schema_name="public",
                table_name="some_table", column_mapping={}, watermark_column="id",
                interval_minutes=15,
            )

    async def test_rejects_another_tenants_connector_id(self, db):
        from app.modules.db_import.service import SyncError, create_sync_schedule

        owner_tenant = await _make_tenant(db, "Owner2")
        attacker_tenant = await _make_tenant(db, "Attacker2")
        connector = ConnectorRegistration(tenant_id=owner_tenant.id, name="Owner's connector", status="active", created_by=1)
        db.add(connector)
        await db.commit()
        await db.refresh(connector)

        with pytest.raises(SyncError):
            await create_sync_schedule(
                db, attacker_tenant.id, user_id=1, entity="sensor_readings",
                connection_id=None, connector_id=connector.id, schema_name=None,
                table_name="some_table", column_mapping={}, watermark_column="id",
                interval_minutes=15,
            )

    async def test_accepts_own_connection_id(self, db):
        from app.modules.db_import.service import create_sync_schedule

        tenant = await _make_tenant(db, "Legit")
        conn = await _make_connection(db, tenant.id)

        schedule = await create_sync_schedule(
            db, tenant.id, user_id=1, entity="sensor_readings",
            connection_id=conn.id, connector_id=None, schema_name="public",
            table_name="some_table", column_mapping={}, watermark_column="id",
            interval_minutes=15,
        )
        assert schedule.id is not None
        assert schedule.tenant_id == tenant.id


class TestDueSyncSchedules:
    async def test_never_run_schedule_is_due(self, db):
        from app.modules.db_import.service import due_sync_schedules

        tenant = await _make_tenant(db, "Due Test")
        conn = await _make_connection(db, tenant.id)
        db.add(SyncSchedule(
            tenant_id=tenant.id, connection_id=conn.id, entity="sensor_readings",
            table_name="t", column_mapping={}, watermark_column="id",
            interval_minutes=15, enabled=True, created_by=1,
        ))
        await db.commit()

        due = await due_sync_schedules(db)
        assert len(due) == 1

    async def test_recently_synced_schedule_is_not_due(self, db):
        from app.modules.db_import.service import due_sync_schedules

        tenant = await _make_tenant(db, "Not Due Test")
        conn = await _make_connection(db, tenant.id)
        db.add(SyncSchedule(
            tenant_id=tenant.id, connection_id=conn.id, entity="sensor_readings",
            table_name="t", column_mapping={}, watermark_column="id",
            interval_minutes=15, enabled=True, created_by=1,
            last_synced_at=datetime.utcnow() - timedelta(minutes=2),
        ))
        await db.commit()

        due = await due_sync_schedules(db)
        assert due == []

    async def test_disabled_schedule_is_never_due(self, db):
        from app.modules.db_import.service import due_sync_schedules

        tenant = await _make_tenant(db, "Disabled Test")
        conn = await _make_connection(db, tenant.id)
        db.add(SyncSchedule(
            tenant_id=tenant.id, connection_id=conn.id, entity="sensor_readings",
            table_name="t", column_mapping={}, watermark_column="id",
            interval_minutes=15, enabled=False, created_by=1,
        ))
        await db.commit()

        due = await due_sync_schedules(db)
        assert due == []


class TestSharedSessionDoesNotPoisonAcrossSchedules:
    """Regression coverage for a real bug found on review: the scheduler runs
    every due schedule (or every tenant's recompute) through ONE shared
    session per tick. Without an explicit rollback after a genuine DB-level
    failure (e.g. a constraint violation), Postgres leaves that session's
    transaction "aborted" — every subsequent statement on it fails too,
    including _mark_sync_failure's own recovery commit, and silently breaks
    every schedule/tenant processed afterward in that same tick.
    """

    async def test_mark_sync_failure_recovers_a_poisoned_transaction(self, db):
        from app.modules.db_import.service import _mark_sync_failure

        tenant = await _make_tenant(db, "Poison Test")
        conn = await _make_connection(db, tenant.id)
        schedule = SyncSchedule(
            tenant_id=tenant.id, connection_id=conn.id, entity="sensor_readings",
            table_name="t", column_mapping={}, watermark_column="id",
            interval_minutes=15, enabled=True, created_by=1,
        )
        db.add(schedule)
        await db.commit()
        await db.refresh(schedule)

        # Force a genuine DB-level failure on this session, the same way a
        # real commit_fn constraint violation would leave it.
        try:
            await db.execute(text("SELECT 1/0"))
            await db.commit()
        except Exception:
            pass  # deliberately NOT rolling back here — that's the scenario being tested

        # _mark_sync_failure must recover on its own (via its internal
        # rollback) rather than raising a second, swallowed exception.
        await _mark_sync_failure(db, schedule, "simulated failure")

        await db.refresh(schedule)
        assert schedule.last_status == "failed"
        assert schedule.consecutive_failures == 1

        # And the session must still be usable afterward — proving no
        # poisoning leaked into whatever the scheduler processes next.
        other_tenant = await _make_tenant(db, "Next In Line")
        assert other_tenant.id is not None


class TestIncrementalReadRows:
    """Regression coverage for a real bug found on review: the adapter's
    since_column/since_value filter fired even when since_value was None,
    generating `WHERE col > NULL` — which SQL never treats as true, so the
    very first sync tick would have silently returned zero rows forever.
    """

    async def test_first_pull_with_no_watermark_returns_all_rows(self, db):
        from app.core.db_adapters import ConnectionParams
        from app.core.db_adapters.postgres import PostgresAdapter

        await db.execute(text("DROP TABLE IF EXISTS sync_test_scratch"))
        await db.execute(text("CREATE TABLE sync_test_scratch (id SERIAL PRIMARY KEY, value TEXT)"))
        await db.execute(text("INSERT INTO sync_test_scratch (value) VALUES ('a'), ('b'), ('c')"))
        await db.commit()

        adapter = PostgresAdapter(ConnectionParams(
            host="localhost", port=5433, username="plantwise", password="plantwise", database="plantwise_test",
        ))
        try:
            rows = await adapter.read_rows("public", "sync_test_scratch", since_column="id", since_value=None)
            assert len(rows) == 3  # not 0 — this is exactly what the NULL-comparison bug would have broken
        finally:
            await adapter.close()
            await db.execute(text("DROP TABLE sync_test_scratch"))
            await db.commit()

    async def test_second_pull_with_watermark_returns_only_new_rows(self, db):
        from app.core.db_adapters import ConnectionParams
        from app.core.db_adapters.postgres import PostgresAdapter

        await db.execute(text("DROP TABLE IF EXISTS sync_test_scratch2"))
        await db.execute(text("CREATE TABLE sync_test_scratch2 (id SERIAL PRIMARY KEY, value TEXT)"))
        await db.execute(text("INSERT INTO sync_test_scratch2 (value) VALUES ('a'), ('b')"))
        await db.commit()

        adapter = PostgresAdapter(ConnectionParams(
            host="localhost", port=5433, username="plantwise", password="plantwise", database="plantwise_test",
        ))
        try:
            first = await adapter.read_rows("public", "sync_test_scratch2", since_column="id", since_value=None)
            assert len(first) == 2
            max_id = max(r["id"] for r in first)

            await db.execute(text("INSERT INTO sync_test_scratch2 (value) VALUES ('c')"))
            await db.commit()

            second = await adapter.read_rows("public", "sync_test_scratch2", since_column="id", since_value=max_id)
            assert len(second) == 1
            assert second[0]["value"] == "c"
        finally:
            await adapter.close()
            await db.execute(text("DROP TABLE sync_test_scratch2"))
            await db.commit()


class TestAssetMetricRangeCommit:
    """The tabular (CSV/DB-sync/quick-form) path for Asset.monitored_metrics —
    same JSON field the per-asset edit form already writes, just given a
    row-shaped source so it can be imported or continuously synced instead of
    only hand-typed once per asset.
    """

    async def test_sets_range_on_an_asset_with_no_prior_metrics(self, db):
        from app.modules.predictive_maintenance.models import Asset
        from app.modules.predictive_maintenance.service import commit_asset_metric_ranges

        tenant = await _make_tenant(db, "Metric Range Plant")
        asset = Asset(tenant_id=tenant.id, asset_code="CNC-04", name="CNC Machine 4", monitored_metrics={})
        db.add(asset)
        await db.commit()

        updated = await commit_asset_metric_ranges(
            db, tenant.id,
            [{"asset_code": "CNC-04", "metric_name": "vibration", "min": 0.0, "max": 8.0, "unit": "mm/s"}],
        )
        assert updated == 1

        await db.refresh(asset)
        assert asset.monitored_metrics == {"vibration": {"min": 0.0, "max": 8.0, "unit": "mm/s"}}

    async def test_adding_a_second_metric_does_not_clobber_the_first(self, db):
        """Regression coverage: re-syncing a table that only has some of an
        asset's metrics must merge into monitored_metrics, not overwrite the
        whole dict and silently drop every previously configured metric."""
        from app.modules.predictive_maintenance.models import Asset
        from app.modules.predictive_maintenance.service import commit_asset_metric_ranges

        tenant = await _make_tenant(db, "Metric Range Plant 2")
        asset = Asset(
            tenant_id=tenant.id, asset_code="CNC-04", name="CNC Machine 4",
            monitored_metrics={"vibration": {"min": 0.0, "max": 8.0, "unit": "mm/s"}},
        )
        db.add(asset)
        await db.commit()

        await commit_asset_metric_ranges(
            db, tenant.id,
            [{"asset_code": "CNC-04", "metric_name": "temperature", "min": 20.0, "max": 70.0, "unit": "C"}],
        )

        await db.refresh(asset)
        assert asset.monitored_metrics == {
            "vibration": {"min": 0.0, "max": 8.0, "unit": "mm/s"},
            "temperature": {"min": 20.0, "max": 70.0, "unit": "C"},
        }

    async def test_unknown_asset_code_is_skipped_not_errored(self, db):
        from app.modules.predictive_maintenance.service import commit_asset_metric_ranges

        tenant = await _make_tenant(db, "Metric Range Plant 3")
        updated = await commit_asset_metric_ranges(
            db, tenant.id,
            [{"asset_code": "DOES-NOT-EXIST", "metric_name": "vibration", "min": 0.0, "max": 8.0, "unit": "mm/s"}],
        )
        assert updated == 0
