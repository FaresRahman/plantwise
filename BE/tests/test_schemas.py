"""Validation tests for Pydantic schemas — business rules that must hold
at the API boundary, independent of any database.
"""

import pytest
from pydantic import ValidationError


class TestAuthSchemas:
    def test_signup_password_too_short(self):
        from app.modules.auth.schemas import SignupRequest
        with pytest.raises(ValidationError) as exc:
            SignupRequest(
                tenant_name="Test",
                full_name="User",
                email="a@b.com",
                password="Ab1",  # too short (< 8)
            )
        errors = exc.value.errors()
        assert any("password" in str(e).lower() for e in errors)

    def test_signup_password_no_uppercase(self):
        from app.modules.auth.schemas import SignupRequest
        with pytest.raises(ValidationError):
            SignupRequest(
                tenant_name="Test",
                full_name="User",
                email="a@b.com",
                password="abcdef1",  # no uppercase
            )

    def test_signup_password_no_lowercase(self):
        from app.modules.auth.schemas import SignupRequest
        with pytest.raises(ValidationError):
            SignupRequest(
                tenant_name="Test",
                full_name="User",
                email="a@b.com",
                password="ABCDEF1",  # no lowercase
            )

    def test_signup_password_no_digit(self):
        from app.modules.auth.schemas import SignupRequest
        with pytest.raises(ValidationError):
            SignupRequest(
                tenant_name="Test",
                full_name="User",
                email="a@b.com",
                password="Abcdefgh",  # no digit
            )

    def test_signup_valid_password(self):
        from app.modules.auth.schemas import SignupRequest
        req = SignupRequest(
            tenant_name="Test Plant",
            full_name="Admin User",
            email="admin@plant.com",
            password="ValidP@ss1",
        )
        assert req.tenant_name == "Test Plant"
        assert req.email == "admin@plant.com"

    def test_invite_request_default_role(self):
        from app.modules.auth.schemas import InviteRequest
        req = InviteRequest(
            email="operator@plant.com",
            full_name="Operator One",
        )
        assert req.role == "operator"

    def test_invite_request_custom_role(self):
        from app.modules.auth.schemas import InviteRequest
        req = InviteRequest(
            email="manager@plant.com",
            full_name="Manager One",
            role="manager",
        )
        assert req.role == "manager"


class TestPMSchemas:
    def test_asset_criticality_validation(self):
        from app.modules.predictive_maintenance.schemas import AssetIn
        with pytest.raises(ValidationError):
            AssetIn(
                asset_code="X",
                name="X",
                category="X",
                line_area="X",
                criticality="extreme",  # invalid
            )

    def test_asset_valid(self):
        from app.modules.predictive_maintenance.schemas import AssetIn
        asset = AssetIn(
            asset_code="CNC-01",
            name="CNC Machine 1",
            category="CNC mill",
            line_area="Line 1",
            criticality="high",
        )
        assert asset.asset_code == "CNC-01"


class TestInventorySchemas:
    def test_item_type_validation(self):
        from app.modules.inventory.schemas import ItemIn
        with pytest.raises(ValidationError):
            ItemIn(
                sku="X",
                name="X",
                item_type="virtual",  # invalid
                unit_of_measure="pcs",
                reorder_point=0,
                supplier_lead_time_days=0,
            )

    def test_item_valid(self):
        from app.modules.inventory.schemas import ItemIn
        item = ItemIn(
            sku="RM-STEEL-1",
            name="Steel sheet 2mm",
            item_type="raw",
            unit_of_measure="sheets",
            reorder_point=300,
            supplier_lead_time_days=3,
        )
        assert item.item_type == "raw"


class TestNotificationSchemas:
    def test_alert_threshold_validation(self):
        from app.modules.notifications.schemas import AlertSettingIn
        # Valid thresholds
        for level in ("low", "med", "high"):
            setting = AlertSettingIn(
                module_key="predictive_maintenance",
                enabled=True,
                urgency_threshold=level,
                recipients=[],
            )
            assert setting.urgency_threshold == level

    def test_alert_invalid_threshold(self):
        from app.modules.notifications.schemas import AlertSettingIn
        with pytest.raises(ValidationError):
            AlertSettingIn(
                module_key="predictive_maintenance",
                enabled=True,
                urgency_threshold="extreme",
                recipients=[],
            )


class TestConfigValidation:
    def test_production_jwt_secret_required(self):
        """In production mode, the default JWT secret must be rejected."""
        import os
        from app.core.config import Settings

        # Should raise ValueError in production with dev secret
        with pytest.raises(ValueError) as exc:
            Settings(
                ENV="production",
                JWT_SECRET="dev-only-secret-change-me",
                DATABASE_URL="postgresql+asyncpg://test@localhost/test",
            )
        assert "JWT_SECRET" in str(exc.value)
