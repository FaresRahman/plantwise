"""Fast, no-DB unit tests for the engine/service functions that are genuinely
pure (take plain values, no AsyncSession, no query) — imported directly from
the real modules, not reimplemented.

Everything else (OEE, run-out projection, defect-rate trend, tolerance
drift, threshold/trend/service-interval detection) has no pure extractable
formula in the actual code — those functions take an AsyncSession and query
real rows, so testing "the same logic, copy-pasted" here would silently
drift from the real implementation the moment either changed. That coverage
lives in test_engines_integration.py instead, which imports and calls the
real async functions against a real Postgres database.
"""

import pytest

from app.modules.predictive_maintenance.models import Recommendation
from app.modules.predictive_maintenance.service import ServiceError, _ensure_transition_allowed
from app.modules.quality.engine import is_spike


# ---------------------------------------------------------------------------
# Spike detection (real quality/engine.py:is_spike — genuinely pure)
# ---------------------------------------------------------------------------

class TestSpikeDetection:
    def test_no_spike_when_no_data(self):
        assert is_spike(0, 0.0, 0.01) is False

    def test_spike_with_2x_increase(self):
        assert is_spike(100, 0.04, 0.01) is True  # 4% vs 1% baseline

    def test_no_spike_with_small_increase(self):
        assert is_spike(100, 0.014, 0.01) is False  # only 0.4pp delta, < 1pp min

    def test_no_spike_below_multiplier(self):
        # 1.4% vs 1% -> 1.4x (below the 1.5x multiplier) -> no spike
        assert is_spike(100, 0.014, 0.01) is False

    def test_spike_with_large_absolute_delta(self):
        # 5% vs 1% -> 5x multiplier, 4pp delta > 1pp -> spike
        assert is_spike(100, 0.05, 0.01) is True


# ---------------------------------------------------------------------------
# Recommendation lifecycle (real predictive_maintenance/service.py — reads
# only rec.status, no DB access, so it's fair game for a fast unit test too;
# also covered end-to-end in test_engines_integration.py)
# ---------------------------------------------------------------------------

def _rec(status: str) -> Recommendation:
    return Recommendation(tenant_id=1, asset_id=1, issue_key="k", issue="i", urgency="high", status=status)


class TestRecommendationLifecycle:
    def test_open_to_acknowledged_allowed(self):
        _ensure_transition_allowed(_rec("open"), "acknowledged")  # no raise

    def test_open_to_actioned_directly_is_allowed(self):
        # Deliberately permissive — passing through "acknowledged" first is
        # the typical path (PRD §5.5) but not enforced; see the comment on
        # _TERMINAL_STATUSES in predictive_maintenance/service.py.
        _ensure_transition_allowed(_rec("open"), "actioned")  # no raise

    def test_terminal_statuses_reject_any_new_transition(self):
        with pytest.raises(ServiceError):
            _ensure_transition_allowed(_rec("actioned"), "acknowledged")
        with pytest.raises(ServiceError):
            _ensure_transition_allowed(_rec("dismissed"), "open")

    def test_repeating_the_current_status_is_a_noop(self):
        _ensure_transition_allowed(_rec("dismissed"), "dismissed")  # no raise — idempotent retry
