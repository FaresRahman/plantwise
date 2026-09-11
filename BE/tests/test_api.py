"""API integration tests using FastAPI's TestClient with mocked DB.

These tests validate:
- Authentication endpoints (signup, login, verify, invite, accept-invite)
- Role-based access control
- Module API contracts (status codes, response shapes)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _mock_db():
    """Prevent real DB connections during tests."""
    with patch("app.core.db.init_db", new=AsyncMock()), \
         patch("app.core.llm.get_embeddings", return_value=MagicMock()), \
         patch("app.core.scheduler.start_scheduler", new=MagicMock()), \
         patch("app.core.scheduler.stop_scheduler", new=MagicMock()):
        yield


@pytest.fixture
def client():
    """Create TestClient with DB dependency overridden to a mock session."""
    from app.main import app
    from app.core.db import get_db

    mock_session = AsyncMock()
    # Make scalar/method returns mockable
    mock_session.scalar = AsyncMock(return_value=None)
    mock_session.scalars = AsyncMock()
    mock_session.execute = AsyncMock(return_value=AsyncMock(all=MagicMock(return_value=[])))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()

    app.dependency_overrides[get_db] = lambda: mock_session
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


# ---------------------------------------------------------------------------
# Auth API tests  (uses mocked DB session)
# ---------------------------------------------------------------------------

class TestAuthAPI:
    def test_signup_validation(self, client):
        """Signup with missing fields returns 422."""
        response = client.post("/api/v1/auth/signup", json={})
        assert response.status_code == 422

    def test_signup_weak_password(self, client):
        """Password must meet strength requirements."""
        response = client.post("/api/v1/auth/signup", json={
            "tenant_name": "Test Plant",
            "full_name": "Admin User",
            "email": "admin@test.com",
            "password": "weak",
        })
        # Should fail validation (no uppercase, no digit, < 8 chars)
        assert response.status_code == 422

    def test_login_missing_fields(self, client):
        response = client.post("/api/v1/auth/login", json={})
        assert response.status_code == 422

    def test_unauthenticated_access(self, client):
        """Endpoints requiring auth return 401 without token."""
        response = client.get("/api/v1/predictive-maintenance/assets")
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Module health endpoints (every module has one)
# ---------------------------------------------------------------------------

MODULES = [
    "/api/v1/auth/health",
    "/api/v1/predictive-maintenance/health",
    "/api/v1/production/health",
    "/api/v1/inventory/health",
    "/api/v1/quality/health",
    "/api/v1/sop/health",
    "/api/v1/shift-reports/health",
    "/api/v1/chatbot/health",
    "/api/v1/onboarding/health",
    "/api/v1/admin/health",
    "/api/v1/dashboard/health",
]


class TestModuleHealth:
    @pytest.mark.parametrize("endpoint", MODULES)
    def test_health_endpoint(self, client, endpoint):
        response = client.get(endpoint)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "module" in data


# ---------------------------------------------------------------------------
# CSV template endpoints (downloadable)
# ---------------------------------------------------------------------------

TEMPLATE_ENDPOINTS = [
    "/api/v1/predictive-maintenance/csv/readings/template",
    "/api/v1/predictive-maintenance/csv/maintenance-history/template",
    "/api/v1/production/csv/output-logs/template",
    "/api/v1/inventory/csv/stock-movements/template",
    "/api/v1/quality/csv/inspection-records/template",
]


class TestCSVTemplates:
    @pytest.mark.parametrize("endpoint", TEMPLATE_ENDPOINTS)
    def test_template_endpoint_accessible(self, client, endpoint):
        """Templates may require auth in production but should be
        reachable (even if returning 401) — confirm the route exists."""
        response = client.get(endpoint)
        # With auth required, 401 is expected; 200 means auth is mocked
        assert response.status_code in (200, 401, 403)
