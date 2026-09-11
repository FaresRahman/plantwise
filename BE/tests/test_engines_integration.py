"""Integration tests for the real engine/service business logic — production
OEE, inventory run-out, quality defect-trend/tolerance-drift, recommendation
lifecycle, and alert dedup — run against a real Postgres database rather
than a mocked session or a hand-copied reimplementation of the formulas.

The previous test_engines.py duplicated each function's logic as a local
pure-Python copy (`compute_oee`, `compute_runout`, `compute_drift`, ...): it
could pass forever even if the real engine.py/service.py code it was meant
to describe drifted away from it, since nothing here ever imported or called
the actual production code. These tests import and call the real functions.

Requires `docker compose up -d postgres` (from BE/) and a `plantwise_test`
database (`CREATE DATABASE plantwise_test;`) — see tests/conftest.py's `db`
fixture, which skips these gracefully (not a failure) if that's not running.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.models_shared import Tenant
from app.modules.auth.models import User
from app.modules.inventory.models import Item, StockMovement
from app.modules.notifications.models import AlertSetting, SentAlert
from app.modules.predictive_maintenance.models import Asset, MaintenanceHistory, Recommendation, SensorReading
from app.modules.production.models import Line, OutputLog
from app.modules.quality.models import Characteristic, InspectionRecord

pytestmark = pytest.mark.integration


async def _make_tenant(db, name="Test Plant") -> Tenant:
    tenant = Tenant(name=name)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


# ---------------------------------------------------------------------------
# Production OEE (real production/engine.py:compute_line_metrics)
# ---------------------------------------------------------------------------

class TestOEEComputationReal:
    async def test_perfect_oee(self, db):
        from app.modules.production.engine import compute_line_metrics

        tenant = await _make_tenant(db)
        line = Line(
            tenant_id=tenant.id, line_code="LINE-1", name="Line 1",
            stations=["Station 1"], products=["Widget"],
            shift_target_units=7200, ideal_cycle_time_seconds=4.0,
        )
        db.add(line)
        await db.commit()
        await db.refresh(line)

        start = datetime(2026, 1, 1, 6, 0)
        end = start + timedelta(minutes=480)
        db.add(OutputLog(
            tenant_id=tenant.id, line_id=line.id, station_id="Station 1",
            timestamp=start + timedelta(minutes=1),
            units_produced=7200, units_good=7200, units_reject=0,
            run_state="run", downtime_minutes=0.0,
        ))
        await db.commit()

        result = await compute_line_metrics(db, tenant.id, line.id, start, end)
        assert result["availability"] == 1.0
        assert result["oee"] == 1.0

    async def test_oee_with_downtime(self, db):
        from app.modules.production.engine import compute_line_metrics

        tenant = await _make_tenant(db)
        line = Line(
            tenant_id=tenant.id, line_code="LINE-2", name="Line 2",
            stations=["Station 1"], products=["Widget"],
            shift_target_units=7200, ideal_cycle_time_seconds=4.0,
        )
        db.add(line)
        await db.commit()
        await db.refresh(line)

        start = datetime(2026, 1, 1, 6, 0)
        end = start + timedelta(minutes=480)
        db.add(OutputLog(
            tenant_id=tenant.id, line_id=line.id, station_id="Station 1",
            timestamp=start + timedelta(minutes=1),
            units_produced=6000, units_good=5800, units_reject=200,
            run_state="run", downtime_minutes=48.0, downtime_reason="Jam",
        ))
        await db.commit()

        result = await compute_line_metrics(db, tenant.id, line.id, start, end)
        # availability = (480-48)/480 = 0.9
        assert result["availability"] == 0.9
        assert abs(result["oee"] - 0.806) < 0.01

    async def test_no_data_is_distinguishable_from_zero(self, db):
        """PRD §5.2: "missing expected data shown as a gap, not a zero"."""
        from app.modules.production.engine import compute_line_metrics

        tenant = await _make_tenant(db)
        line = Line(tenant_id=tenant.id, line_code="LINE-3", name="Line 3", shift_target_units=100)
        db.add(line)
        await db.commit()
        await db.refresh(line)

        start = datetime(2026, 1, 1, 6, 0)
        end = start + timedelta(minutes=480)
        result = await compute_line_metrics(db, tenant.id, line.id, start, end)
        assert result["has_data"] is False

    async def test_oee_history_bucket_includes_units_and_target(self, db):
        """The dashboard's plant-wide OEE trend chart — same
        compute_line_metrics under the hood, just bucketed per day, and must
        carry total_units/shift_target_units through so the chart can show
        actual vs. target, not just the OEE percentage."""
        from app.modules.production.engine import compute_oee_history

        tenant = await _make_tenant(db)
        line = Line(
            tenant_id=tenant.id, line_code="LINE-4", name="Line 4",
            stations=["Station 1"], products=["Widget"],
            shift_target_units=800, ideal_cycle_time_seconds=4.0,
        )
        db.add(line)
        await db.commit()
        await db.refresh(line)

        end = datetime(2026, 1, 2, 0, 0)
        db.add(OutputLog(
            tenant_id=tenant.id, line_id=line.id, station_id="Station 1",
            timestamp=end - timedelta(hours=12),
            units_produced=500, units_good=480, units_reject=20,
            run_state="run", downtime_minutes=30.0, downtime_reason="Jam",
        ))
        await db.commit()

        history = await compute_oee_history(db, tenant.id, line.id, 14, end)
        assert len(history) == 14
        last = history[-1]
        assert last["total_units"] == 500
        assert last["shift_target_units"] == 800

    async def test_oee_history_unknown_line_returns_empty(self, db):
        from app.modules.production.engine import compute_oee_history

        tenant = await _make_tenant(db)
        history = await compute_oee_history(db, tenant.id, 999999, 14, datetime(2026, 1, 2, 0, 0))
        assert history == []


# ---------------------------------------------------------------------------
# Inventory run-out projection (real inventory/engine.py:compute_item_projection)
# ---------------------------------------------------------------------------

class TestInventoryProjectionReal:
    async def _make_item(self, db, tenant_id, **overrides):
        defaults = dict(sku="RM-1", name="Raw material 1", reorder_point=300, supplier_lead_time_days=3)
        defaults.update(overrides)
        item = Item(tenant_id=tenant_id, **defaults)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    async def test_normal_stock(self, db):
        from app.modules.inventory.engine import compute_item_projection

        tenant = await _make_tenant(db)
        item = await self._make_item(db, tenant.id)
        db.add(StockMovement(tenant_id=tenant.id, item_id=item.id, timestamp=datetime.utcnow(), current_qty=500, qty_out=50))
        await db.commit()

        result = await compute_item_projection(db, tenant.id, item)
        assert result["days_to_runout"] == 10.0
        assert result["is_low"] is False

    async def test_below_reorder_point(self, db):
        from app.modules.inventory.engine import compute_item_projection

        tenant = await _make_tenant(db)
        item = await self._make_item(db, tenant.id, sku="RM-2")
        db.add(StockMovement(tenant_id=tenant.id, item_id=item.id, timestamp=datetime.utcnow(), current_qty=200, qty_out=10))
        await db.commit()

        result = await compute_item_projection(db, tenant.id, item)
        assert result["is_low"] is True

    async def test_runout_within_lead_time(self, db):
        from app.modules.inventory.engine import compute_item_projection

        tenant = await _make_tenant(db)
        item = await self._make_item(db, tenant.id, sku="RM-3", reorder_point=50, supplier_lead_time_days=3)
        db.add(StockMovement(tenant_id=tenant.id, item_id=item.id, timestamp=datetime.utcnow(), current_qty=100, qty_out=50))
        await db.commit()

        result = await compute_item_projection(db, tenant.id, item)
        assert result["days_to_runout"] == 2.0
        assert result["is_low"] is True

    async def test_no_consumption_has_no_runout_date(self, db):
        from app.modules.inventory.engine import compute_item_projection

        tenant = await _make_tenant(db)
        item = await self._make_item(db, tenant.id, sku="RM-4")
        db.add(StockMovement(tenant_id=tenant.id, item_id=item.id, timestamp=datetime.utcnow(), current_qty=500, qty_out=0))
        await db.commit()

        result = await compute_item_projection(db, tenant.id, item)
        assert result["days_to_runout"] is None

    async def test_no_movements_not_flagged_low(self, db):
        from app.modules.inventory.engine import compute_item_projection

        tenant = await _make_tenant(db)
        item = await self._make_item(db, tenant.id, sku="RM-5", reorder_point=300)

        result = await compute_item_projection(db, tenant.id, item)
        assert result["has_data"] is False
        assert result["is_low"] is False

    async def test_bom_implied_consumption_feeds_component_projection(self, db):
        """PRD §6.4's own example depends on BOM demand, not just trailing
        qty_out — regression test for the fix that made bill_of_materials
        actually affect a component's run-out projection.
        """
        from app.modules.inventory.engine import compute_item_projection

        tenant = await _make_tenant(db)
        steel = await self._make_item(db, tenant.id, sku="RM-STEEL", reorder_point=100, supplier_lead_time_days=3)
        widget = await self._make_item(
            db, tenant.id, sku="WIDGET-A", name="Widget A", item_type="finished",
            bill_of_materials={"RM-STEEL": 2.0},
        )
        # Steel has no directly-logged consumption at all...
        db.add(StockMovement(tenant_id=tenant.id, item_id=steel.id, timestamp=datetime.utcnow(), current_qty=1000, qty_out=0))
        # ...but Widget-A is being produced at 100 units/day, implying 200 units/day of steel.
        db.add(StockMovement(tenant_id=tenant.id, item_id=widget.id, timestamp=datetime.utcnow(), current_qty=100, qty_in=100))
        await db.commit()

        result = await compute_item_projection(db, tenant.id, steel)
        assert result["daily_consumption"] == 200.0
        assert result["days_to_runout"] == 5.0


# ---------------------------------------------------------------------------
# Quality defect-rate trend + tolerance drift (real quality/engine.py)
# ---------------------------------------------------------------------------

class TestQualityTrendReal:
    async def test_spike_detected_from_real_rows(self, db):
        from app.modules.quality.engine import compute_defect_trend

        tenant = await _make_tenant(db)
        now = datetime.utcnow()
        baseline_ts = now - timedelta(days=5)
        recent_ts = now - timedelta(hours=1)

        # Baseline window (>3 days ago): 10 inspections, 1 fail -> 10% ... use
        # a low baseline rate, then a much higher recent rate to trip the spike.
        for i in range(20):
            db.add(InspectionRecord(
                tenant_id=tenant.id, part_id="P-1", timestamp=baseline_ts,
                characteristic_name="bore", measured_value=25.0, pass_fail=True,
                line_id="LINE-1", station_id="Station 1", inspector="qc",
            ))
        db.add(InspectionRecord(
            tenant_id=tenant.id, part_id="P-1", timestamp=baseline_ts,
            characteristic_name="bore", measured_value=25.0, pass_fail=False,
            defect_type="burr", line_id="LINE-1", station_id="Station 1", inspector="qc",
        ))
        # Recent window (last 3 days): high fail rate.
        for i in range(5):
            db.add(InspectionRecord(
                tenant_id=tenant.id, part_id="P-1", timestamp=recent_ts,
                characteristic_name="bore", measured_value=25.4,
                pass_fail=(i >= 4), defect_type=None if i >= 4 else "surface scratch",
                line_id="LINE-1", station_id="Station 1", inspector="qc",
            ))
        await db.commit()

        trend = await compute_defect_trend(db, tenant.id, "P-1", "bore", line_id="LINE-1")
        assert trend["is_spike"] is True
        assert trend["recent_rate"] > trend["baseline_rate"]

    async def test_line_scoping_isolates_rates_per_line(self, db):
        """Regression test for the line/station-scoping fix — a part
        inspected on two lines must not have its rates blended together.
        """
        from app.modules.quality.engine import compute_defect_trend

        tenant = await _make_tenant(db)
        now = datetime.utcnow()
        recent_ts = now - timedelta(hours=1)

        # Line 1: all fail. Line 2: all pass. Same part+characteristic.
        for _ in range(5):
            db.add(InspectionRecord(
                tenant_id=tenant.id, part_id="P-2", timestamp=recent_ts,
                characteristic_name="length", measured_value=10.0, pass_fail=False,
                defect_type="short", line_id="LINE-1", station_id="Station 1",
            ))
            db.add(InspectionRecord(
                tenant_id=tenant.id, part_id="P-2", timestamp=recent_ts,
                characteristic_name="length", measured_value=10.0, pass_fail=True,
                line_id="LINE-2", station_id="Station 1",
            ))
        await db.commit()

        line1_trend = await compute_defect_trend(db, tenant.id, "P-2", "length", line_id="LINE-1")
        line2_trend = await compute_defect_trend(db, tenant.id, "P-2", "length", line_id="LINE-2")
        assert line1_trend["recent_rate"] == 1.0
        assert line2_trend["recent_rate"] == 0.0

    async def test_tolerance_drift_toward_limit(self, db):
        from app.modules.quality.engine import compute_tolerance_drift

        tenant = await _make_tenant(db)
        now = datetime.utcnow()
        baseline_ts = now - timedelta(days=5)
        recent_ts = now - timedelta(hours=1)

        db.add(InspectionRecord(
            tenant_id=tenant.id, part_id="P-3", timestamp=baseline_ts,
            characteristic_name="bore", measured_value=12.01, pass_fail=True,
        ))
        db.add(InspectionRecord(
            tenant_id=tenant.id, part_id="P-3", timestamp=recent_ts,
            characteristic_name="bore", measured_value=12.05, pass_fail=True,
        ))
        await db.commit()

        drift = await compute_tolerance_drift(db, tenant.id, "P-3", "bore", nominal_value=12.0, tolerance=0.05)
        assert drift["is_drifting_toward_limit"] is True
        assert drift["is_approaching_limit"] is True

    async def test_get_recent_measurements_returns_raw_values_in_order(self, db):
        """The "based on the values" trend chart — actual measured values
        over time, distinct from the pass/fail rate comparison above."""
        from app.modules.quality.models import Characteristic
        from app.modules.quality.service import get_recent_measurements

        tenant = await _make_tenant(db)
        char = Characteristic(
            tenant_id=tenant.id, part_id="PART-A22", characteristic_name="Bore Diameter",
            nominal_value=12.0, tolerance=0.05, line_id="LINE-3", station_id="ST-2",
        )
        db.add(char)
        await db.commit()
        await db.refresh(char)

        now = datetime.utcnow()
        db.add(InspectionRecord(
            tenant_id=tenant.id, part_id="PART-A22", timestamp=now - timedelta(hours=2),
            characteristic_name="Bore Diameter", measured_value=12.01, pass_fail=True,
            line_id="LINE-3", station_id="ST-2", inspector="qc",
        ))
        db.add(InspectionRecord(
            tenant_id=tenant.id, part_id="PART-A22", timestamp=now - timedelta(hours=1),
            characteristic_name="Bore Diameter", measured_value=12.08, pass_fail=False,
            defect_type="surface scratch", line_id="LINE-3", station_id="ST-2", inspector="qc",
        ))
        await db.commit()

        measurements = await get_recent_measurements(db, tenant.id, char, days=30)
        assert len(measurements) == 2
        assert measurements[0]["measured_value"] == 12.01
        assert measurements[1]["measured_value"] == 12.08
        assert measurements[1]["pass_fail"] is False


# ---------------------------------------------------------------------------
# Predictive maintenance detection rules (real predictive_maintenance/engine.py)
# ---------------------------------------------------------------------------

class TestPredictiveMaintenanceEngineReal:
    async def _make_asset(self, db, tenant_id, **overrides) -> Asset:
        defaults = dict(
            asset_code="CNC-1", name="CNC Machine 1", criticality="high",
            monitored_metrics={"vibration": {"min": 0, "max": 3.0, "unit": "mm/s"}},
        )
        defaults.update(overrides)
        asset = Asset(tenant_id=tenant_id, **defaults)
        db.add(asset)
        await db.commit()
        await db.refresh(asset)
        return asset

    async def test_threshold_breach_creates_high_urgency_recommendation(self, db):
        from app.modules.predictive_maintenance.engine import _check_threshold

        tenant = await _make_tenant(db)
        asset = await self._make_asset(db, tenant.id)
        # Max is 3.0mm/s; 4.8 is a 60% breach of the 3.0-wide range -> "high".
        db.add(SensorReading(tenant_id=tenant.id, asset_id=asset.id, timestamp=datetime.utcnow(), metric="vibration", value=4.8, unit="mm/s"))
        await db.commit()

        await _check_threshold(db, tenant.id, asset, "vibration", mn=0, mx=3.0, unit="mm/s")

        rec = await db.scalar(select(Recommendation).where(Recommendation.tenant_id == tenant.id, Recommendation.asset_id == asset.id))
        assert rec is not None
        assert rec.urgency == "high"
        assert rec.issue_key == "vibration:threshold"
        assert rec.status == "open"

    async def test_within_range_creates_no_recommendation(self, db):
        from app.modules.predictive_maintenance.engine import _check_threshold

        tenant = await _make_tenant(db)
        asset = await self._make_asset(db, tenant.id)
        db.add(SensorReading(tenant_id=tenant.id, asset_id=asset.id, timestamp=datetime.utcnow(), metric="vibration", value=1.5, unit="mm/s"))
        await db.commit()

        await _check_threshold(db, tenant.id, asset, "vibration", mn=0, mx=3.0, unit="mm/s")

        rec = await db.scalar(select(Recommendation).where(Recommendation.tenant_id == tenant.id, Recommendation.asset_id == asset.id))
        assert rec is None

    async def test_rising_trend_toward_limit_creates_recommendation(self, db):
        from app.modules.predictive_maintenance.engine import _check_trend

        tenant = await _make_tenant(db)
        asset = await self._make_asset(db, tenant.id)
        now = datetime.utcnow()
        # Matches the PRD's own §4.1 worked example: 2.1 -> 4.8 mm/s over 9 days.
        for days_ago, value in [(9, 2.1), (6, 2.8), (3, 3.6), (1, 4.2), (0, 4.8)]:
            db.add(SensorReading(
                tenant_id=tenant.id, asset_id=asset.id, timestamp=now - timedelta(days=days_ago),
                metric="vibration", value=value, unit="mm/s",
            ))
        await db.commit()

        await _check_trend(db, tenant.id, asset, "vibration", mn=0, mx=3.0, unit="mm/s")

        rec = await db.scalar(select(Recommendation).where(Recommendation.tenant_id == tenant.id, Recommendation.issue_key == "vibration:trend"))
        assert rec is not None
        assert rec.urgency == "high"  # already past the limit -> 0 days to breach

    async def test_service_interval_overdue_creates_high_urgency_recommendation(self, db):
        from app.modules.predictive_maintenance.engine import _check_service_interval

        tenant = await _make_tenant(db)
        asset = await self._make_asset(
            db, tenant.id, asset_code="COMP-1", name="Compressor 1",
            install_date=date.today() - timedelta(days=30),
        )
        # No maintenance history at all -> falls back to install_date as the
        # reference point; 30 days = 720 running-hours, well past a 500h interval.
        await _check_service_interval(db, tenant.id, asset, "lubrication", interval_hours=500)

        rec = await db.scalar(select(Recommendation).where(Recommendation.tenant_id == tenant.id, Recommendation.issue_key == "lubrication:interval"))
        assert rec is not None
        assert rec.urgency == "high"

    async def test_service_interval_uses_most_recent_matching_history_not_install_date(self, db):
        from app.modules.predictive_maintenance.engine import _check_service_interval

        tenant = await _make_tenant(db)
        asset = await self._make_asset(
            db, tenant.id, asset_code="COMP-2", name="Compressor 2",
            install_date=date.today() - timedelta(days=1000),  # would be wildly overdue if used
        )
        db.add(MaintenanceHistory(
            tenant_id=tenant.id, asset_id=asset.id, date=date.today() - timedelta(hours=1),
            type="preventive", description="Routine lubrication service", downtime_hours=0.0,
        ))
        await db.commit()

        await _check_service_interval(db, tenant.id, asset, "lubrication", interval_hours=500)

        rec = await db.scalar(select(Recommendation).where(Recommendation.tenant_id == tenant.id, Recommendation.issue_key == "lubrication:interval"))
        assert rec is None  # only ~1 hour since the matching service record -> nowhere near due


# ---------------------------------------------------------------------------
# Failure-case signature capture (real predictive_maintenance/service.py +
# engine.py) — the auto-built case library behind historical pattern matching.
# ---------------------------------------------------------------------------

class TestFailureCaseSignatureCapture:
    async def _make_asset(self, db, tenant_id, **overrides) -> Asset:
        defaults = dict(
            asset_code="CNC-SIG", name="CNC Signature Test", criticality="high",
            monitored_metrics={"vibration": {"min": 0, "max": 3.0, "unit": "mm/s"}},
        )
        defaults.update(overrides)
        asset = Asset(tenant_id=tenant_id, **defaults)
        db.add(asset)
        await db.commit()
        await db.refresh(asset)
        return asset

    async def test_corrective_commit_captures_a_signature(self, db):
        from app.modules.predictive_maintenance.models import FailureCaseSignature
        from app.modules.predictive_maintenance.service import commit_maintenance_history

        tenant = await _make_tenant(db)
        asset = await self._make_asset(db, tenant.id)
        event_date = date.today()
        event_dt = datetime.combine(event_date, datetime.min.time())
        for days_ago, value in [(9, 2.1), (6, 2.8), (3, 3.6), (1, 4.2), (0, 4.8)]:
            db.add(SensorReading(
                tenant_id=tenant.id, asset_id=asset.id, timestamp=event_dt - timedelta(days=days_ago),
                metric="vibration", value=value, unit="mm/s",
            ))
        await db.commit()

        await commit_maintenance_history(db, tenant.id, [{
            "asset_id": asset.asset_code, "date": event_date, "type": "corrective",
            "description": "Bearing failure", "downtime_hours": 4.0, "parts_replaced": "Drive shaft bearing",
        }])

        sig = await db.scalar(
            select(FailureCaseSignature).where(FailureCaseSignature.tenant_id == tenant.id, FailureCaseSignature.asset_id == asset.id)
        )
        assert sig is not None
        assert sig.metric == "vibration"
        assert sig.slope > 0  # rising, matching the readings above
        assert sig.unit == "mm/s"

    async def test_preventive_commit_captures_no_signature(self, db):
        from app.modules.predictive_maintenance.models import FailureCaseSignature
        from app.modules.predictive_maintenance.service import commit_maintenance_history

        tenant = await _make_tenant(db)
        asset = await self._make_asset(db, tenant.id, asset_code="CNC-SIG-2")

        await commit_maintenance_history(db, tenant.id, [{
            "asset_id": asset.asset_code, "date": date.today(), "type": "preventive",
            "description": "Routine lubrication", "downtime_hours": 1.0, "parts_replaced": None,
        }])

        sig = await db.scalar(
            select(FailureCaseSignature).where(FailureCaseSignature.tenant_id == tenant.id, FailureCaseSignature.asset_id == asset.id)
        )
        assert sig is None  # only corrective events build the failure-case library


# ---------------------------------------------------------------------------
# Historical pattern matching (real predictive_maintenance/engine.py) —
# _check_historical_pattern_match, the "why/before it stops/reason" check.
# ---------------------------------------------------------------------------

class TestHistoricalPatternMatchReal:
    async def _make_asset(self, db, tenant_id, **overrides) -> Asset:
        defaults = dict(
            asset_code="CNC-PAT", name="CNC Pattern Test", criticality="high",
            monitored_metrics={"vibration": {"min": 0, "max": 3.0, "unit": "mm/s"}},
        )
        defaults.update(overrides)
        asset = Asset(tenant_id=tenant_id, **defaults)
        db.add(asset)
        await db.commit()
        await db.refresh(asset)
        return asset

    async def _seed_case(self, db, tenant_id, asset, days_ago_start=40, direction=1) -> MaintenanceHistory:
        """A past corrective event with a real captured signature, the way
        commit_maintenance_history builds one from ordinary usage."""
        from app.modules.predictive_maintenance.service import commit_maintenance_history

        event_date = date.today() - timedelta(days=days_ago_start - 9)
        event_dt = datetime.combine(event_date, datetime.min.time())
        base = 2.0
        for days_ago, offset in [(9, 0.0), (6, 0.7), (3, 1.5), (1, 2.1), (0, 2.7)]:
            value = base + direction * offset
            db.add(SensorReading(
                tenant_id=tenant_id, asset_id=asset.id, timestamp=event_dt - timedelta(days=days_ago),
                metric="vibration", value=value, unit="mm/s",
            ))
        await db.commit()

        await commit_maintenance_history(db, tenant_id, [{
            "asset_id": asset.asset_code, "date": event_date, "type": "corrective",
            "description": "Bearing wear", "downtime_hours": 3.0, "parts_replaced": "Bearing",
        }])
        return await db.scalar(
            select(MaintenanceHistory).where(MaintenanceHistory.tenant_id == tenant_id, MaintenanceHistory.asset_id == asset.id)
        )

    async def test_matching_rising_trend_fires_recommendation_citing_the_case(self, db):
        from app.modules.predictive_maintenance.engine import _check_historical_pattern_match

        tenant = await _make_tenant(db)
        asset = await self._make_asset(db, tenant.id)
        case = await self._seed_case(db, tenant.id, asset, direction=1)

        now = datetime.utcnow()
        for days_ago, value in [(9, 2.1), (6, 2.8), (3, 3.6), (1, 4.2), (0, 4.8)]:
            db.add(SensorReading(
                tenant_id=tenant.id, asset_id=asset.id, timestamp=now - timedelta(days=days_ago),
                metric="vibration", value=value, unit="mm/s",
            ))
        await db.commit()

        await _check_historical_pattern_match(db, tenant.id, asset)

        rec = await db.scalar(
            select(Recommendation).where(Recommendation.tenant_id == tenant.id, Recommendation.issue_key == f"pattern:mh{case.id}")
        )
        assert rec is not None
        assert "Bearing" in rec.evidence or "Bearing" in rec.recommended_action
        assert str(case.date) in rec.evidence

    async def test_opposite_direction_does_not_match(self, db):
        from app.modules.predictive_maintenance.engine import _check_historical_pattern_match

        tenant = await _make_tenant(db)
        asset = await self._make_asset(db, tenant.id, asset_code="CNC-PAT-2")
        await self._seed_case(db, tenant.id, asset, direction=1)  # past case was RISING

        now = datetime.utcnow()  # current trend is FALLING — should not match
        for days_ago, value in [(9, 4.8), (6, 4.2), (3, 3.6), (1, 2.8), (0, 2.1)]:
            db.add(SensorReading(
                tenant_id=tenant.id, asset_id=asset.id, timestamp=now - timedelta(days=days_ago),
                metric="vibration", value=value, unit="mm/s",
            ))
        await db.commit()

        await _check_historical_pattern_match(db, tenant.id, asset)

        rec = await db.scalar(
            select(Recommendation).where(Recommendation.tenant_id == tenant.id, Recommendation.asset_id == asset.id)
        )
        assert rec is None

    async def test_multi_metric_asset_requires_corroboration(self, db):
        """An asset monitoring two metrics needs both to agree with a past
        case before firing — a single matching metric alone isn't enough
        corroboration for a joint pattern claim."""
        from app.modules.predictive_maintenance.engine import _check_historical_pattern_match
        from app.modules.predictive_maintenance.service import commit_maintenance_history

        tenant = await _make_tenant(db)
        asset = await self._make_asset(
            db, tenant.id, asset_code="CNC-PAT-3",
            monitored_metrics={
                "vibration": {"min": 0, "max": 3.0, "unit": "mm/s"},
                "temperature": {"min": 0, "max": 80.0, "unit": "C"},
            },
        )

        # Past case: BOTH vibration and temperature rose together.
        event_date = date.today() - timedelta(days=31)
        event_dt = datetime.combine(event_date, datetime.min.time())
        for days_ago, vib, temp in [(9, 2.0, 60.0), (6, 2.5, 66.0), (3, 3.1, 72.0), (1, 3.6, 76.0), (0, 4.0, 79.0)]:
            db.add(SensorReading(tenant_id=tenant.id, asset_id=asset.id, timestamp=event_dt - timedelta(days=days_ago), metric="vibration", value=vib, unit="mm/s"))
            db.add(SensorReading(tenant_id=tenant.id, asset_id=asset.id, timestamp=event_dt - timedelta(days=days_ago), metric="temperature", value=temp, unit="C"))
        await db.commit()
        await commit_maintenance_history(db, tenant.id, [{
            "asset_id": asset.asset_code, "date": event_date, "type": "corrective",
            "description": "Overheating bearing", "downtime_hours": 5.0, "parts_replaced": "Bearing + coolant line",
        }])

        # Current window: ONLY vibration rises this time; temperature is flat.
        now = datetime.utcnow()
        for days_ago, vib in [(9, 2.1), (6, 2.8), (3, 3.6), (1, 4.2), (0, 4.8)]:
            db.add(SensorReading(tenant_id=tenant.id, asset_id=asset.id, timestamp=now - timedelta(days=days_ago), metric="vibration", value=vib, unit="mm/s"))
        for days_ago in (9, 6, 3, 1, 0):
            db.add(SensorReading(tenant_id=tenant.id, asset_id=asset.id, timestamp=now - timedelta(days=days_ago), metric="temperature", value=70.0, unit="C"))
        await db.commit()

        await _check_historical_pattern_match(db, tenant.id, asset)

        rec = await db.scalar(
            select(Recommendation).where(Recommendation.tenant_id == tenant.id, Recommendation.asset_id == asset.id)
        )
        assert rec is None  # only one of the two monitored metrics corroborates -> not enough


# ---------------------------------------------------------------------------
# Recommendation lifecycle (real predictive_maintenance/service.py)
# ---------------------------------------------------------------------------

class TestRecommendationLifecycleReal:
    """No DB needed — _ensure_transition_allowed only reads rec.status — but
    imports and exercises the actual service function and real ORM class,
    not a hand-copied state table.
    """

    def _rec(self, status: str) -> Recommendation:
        return Recommendation(
            tenant_id=1, asset_id=1, issue_key="k", issue="i", urgency="high", status=status,
        )

    def test_open_to_acknowledged_allowed(self):
        from app.modules.predictive_maintenance.service import _ensure_transition_allowed

        _ensure_transition_allowed(self._rec("open"), "acknowledged")  # no raise

    def test_terminal_status_rejects_transition(self):
        from app.modules.predictive_maintenance.service import ServiceError, _ensure_transition_allowed

        with pytest.raises(ServiceError):
            _ensure_transition_allowed(self._rec("actioned"), "acknowledged")

    def test_same_status_is_a_noop(self):
        from app.modules.predictive_maintenance.service import _ensure_transition_allowed

        _ensure_transition_allowed(self._rec("dismissed"), "dismissed")  # no raise — idempotent retry


# ---------------------------------------------------------------------------
# Alert dedup (real notifications/service.py)
# ---------------------------------------------------------------------------

class TestAlertDedupReal:
    async def _make_admin(self, db, tenant_id) -> User:
        user = User(
            tenant_id=tenant_id, email="admin@test.com", hashed_password="x",
            full_name="Admin", role="admin", is_verified=True,
        )
        db.add(user)
        await db.commit()
        return user

    async def test_trigger_then_dedup_then_clear_refires(self, db, monkeypatch):
        from app.modules.notifications import service as notif_service

        sent = []
        monkeypatch.setattr(notif_service, "send_email", lambda **kw: sent.append(kw))

        tenant = await _make_tenant(db)
        await self._make_admin(db, tenant.id)
        db.add(AlertSetting(tenant_id=tenant.id, module="inventory", enabled=True, urgency_threshold="high"))
        await db.commit()

        await notif_service.trigger_generic_alert(
            db, tenant.id, "inventory", title="Steel low stock", message="m", dashboard_link="/inventory",
        )
        assert len(sent) == 1

        # Same title again — still "sent" (dedup ledger present) — no second email.
        await notif_service.trigger_generic_alert(
            db, tenant.id, "inventory", title="Steel low stock", message="m2", dashboard_link="/inventory",
        )
        assert len(sent) == 1

        await notif_service.clear_generic_alert(db, tenant.id, "inventory", "Steel low stock")

        # Recurrence after clearing re-fires.
        await notif_service.trigger_generic_alert(
            db, tenant.id, "inventory", title="Steel low stock", message="m3", dashboard_link="/inventory",
        )
        assert len(sent) == 2

    async def test_no_recipients_does_not_write_dedup_row(self, db, monkeypatch):
        """Regression test: an alert that never reaches anyone must not be
        recorded as "sent" — otherwise it can never fire once a recipient is
        finally configured, since the (now-stale) SentAlert row would still
        dedup it away.
        """
        from app.modules.notifications import service as notif_service

        sent = []
        monkeypatch.setattr(notif_service, "send_email", lambda **kw: sent.append(kw))

        tenant = await _make_tenant(db)  # no User rows at all — no recipients
        db.add(AlertSetting(tenant_id=tenant.id, module="inventory", enabled=True, urgency_threshold="high"))
        await db.commit()

        await notif_service.trigger_generic_alert(
            db, tenant.id, "inventory", title="Steel low stock", message="m", dashboard_link="/inventory",
        )
        assert sent == []

        row = await db.scalar(select(SentAlert).where(SentAlert.tenant_id == tenant.id))
        assert row is None


# ---------------------------------------------------------------------------
# Dashboard "Issues" trend chart (predictive_maintenance/service.py)
# ---------------------------------------------------------------------------

class TestRecommendationTrend:
    async def _make_asset(self, db, tenant_id, **overrides) -> Asset:
        defaults = dict(asset_code="CNC-1", name="CNC Machine 1", criticality="high")
        defaults.update(overrides)
        asset = Asset(tenant_id=tenant_id, **defaults)
        db.add(asset)
        await db.commit()
        await db.refresh(asset)
        return asset

    async def test_buckets_by_day_and_urgency(self, db):
        from app.modules.predictive_maintenance.service import get_recommendation_trend

        tenant = await _make_tenant(db)
        asset = await self._make_asset(db, tenant.id)
        now = datetime.utcnow()
        db.add(Recommendation(
            tenant_id=tenant.id, asset_id=asset.id, issue_key="k1", issue="i1", urgency="high", created_at=now,
        ))
        db.add(Recommendation(
            tenant_id=tenant.id, asset_id=asset.id, issue_key="k2", issue="i2", urgency="med", created_at=now,
        ))
        await db.commit()

        trend = await get_recommendation_trend(db, tenant.id, granularity="day")
        assert len(trend) == 1
        assert trend[0]["high"] == 1
        assert trend[0]["med"] == 1
        assert trend[0]["low"] == 0
        assert trend[0]["total"] == 2

    async def test_urgency_filter_narrows_the_counted_set(self, db):
        from app.modules.predictive_maintenance.service import get_recommendation_trend

        tenant = await _make_tenant(db)
        asset = await self._make_asset(db, tenant.id)
        now = datetime.utcnow()
        db.add(Recommendation(tenant_id=tenant.id, asset_id=asset.id, issue_key="k1", issue="i1", urgency="high", created_at=now))
        db.add(Recommendation(tenant_id=tenant.id, asset_id=asset.id, issue_key="k2", issue="i2", urgency="low", created_at=now))
        await db.commit()

        trend = await get_recommendation_trend(db, tenant.id, granularity="day", urgency="high")
        assert len(trend) == 1
        assert trend[0]["high"] == 1
        assert trend[0]["low"] == 0
        assert trend[0]["total"] == 1

    async def test_outside_the_lookback_window_is_excluded(self, db):
        from app.modules.predictive_maintenance.service import get_recommendation_trend

        tenant = await _make_tenant(db)
        asset = await self._make_asset(db, tenant.id)
        old = datetime.utcnow() - timedelta(days=400)  # past the "day" granularity's 30-day lookback
        db.add(Recommendation(tenant_id=tenant.id, asset_id=asset.id, issue_key="k1", issue="old", urgency="high", created_at=old))
        await db.commit()

        trend = await get_recommendation_trend(db, tenant.id, granularity="day")
        assert trend == []
