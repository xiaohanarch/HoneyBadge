"""Tests for JWT auth module (src/honeybadge/server/auth.py)."""

import time

import pytest

from honeybadge.server.auth import (
    DEMO_USERS,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    user_to_response,
)

# Shared secret used for all token tests
_SECRET = "test-jwt-secret-key"


class TestDemoUsers:
    """Tests for DEMO_USERS dict structure and content."""

    def test_demo_users_has_five_entries(self):
        """DEMO_USERS should contain exactly five users."""
        assert len(DEMO_USERS) == 5

    def test_admin_user_exists(self):
        """admin user should be present."""
        assert "admin" in DEMO_USERS

    def test_analyst_user_exists(self):
        """analyst user should be present."""
        assert "analyst" in DEMO_USERS

    def test_auditor_user_exists(self):
        """auditor user should be present."""
        assert "auditor" in DEMO_USERS

    def test_procurement_lead_user_exists(self):
        """procurement_lead user should be present."""
        assert "procurement_lead" in DEMO_USERS

    def test_subsidiary_lead_user_exists(self):
        """subsidiary_lead user should be present."""
        assert "subsidiary_lead" in DEMO_USERS

    def test_procurement_lead_fields(self):
        """procurement_lead should have correct fields."""
        user = DEMO_USERS["procurement_lead"]
        assert user["username"] == "procurement_lead"
        assert user["display_name"] == "采购部门领导"
        assert "analyst" in user["roles"]
        assert user["org_id"] == 1

    def test_subsidiary_lead_fields(self):
        """subsidiary_lead should have correct fields and org_id=2."""
        user = DEMO_USERS["subsidiary_lead"]
        assert user["username"] == "subsidiary_lead"
        assert user["display_name"] == "子公司领导"
        assert "analyst" in user["roles"]
        assert user["org_id"] == 2

    def test_admin_fields(self):
        """admin user should have correct fields."""
        user = DEMO_USERS["admin"]
        assert user["username"] == "admin"
        assert "password_hash" in user
        assert user["display_name"] == "系统管理员"
        assert "admin" in user["roles"]
        assert user["org_id"] == 1

    def test_analyst_fields(self):
        """analyst user should have correct fields."""
        user = DEMO_USERS["analyst"]
        assert user["username"] == "analyst"
        assert user["display_name"] == "数据分析师"
        assert "analyst" in user["roles"]
        assert user["org_id"] == 1

    def test_auditor_fields(self):
        """auditor user should have correct fields."""
        user = DEMO_USERS["auditor"]
        assert user["username"] == "auditor"
        assert user["display_name"] == "审计员"
        assert "auditor" in user["roles"]
        assert user["org_id"] == 1

    def test_passwords_are_hashed(self):
        """password_hash should not be plaintext."""
        for user in DEMO_USERS.values():
            assert user["password_hash"] != "admin123"
            assert user["password_hash"] != "analyst123"
            assert user["password_hash"] != "auditor123"
            # bcrypt hashes start with $2b$
            assert user["password_hash"].startswith("$2")


class TestAuthenticateUser:
    """Tests for authenticate_user function."""

    def test_authenticate_admin_success(self):
        """Should return user dict for valid admin credentials."""
        user = authenticate_user("admin", "admin123")
        assert user is not None
        assert user["username"] == "admin"

    def test_authenticate_analyst_success(self):
        """Should return user dict for valid analyst credentials."""
        user = authenticate_user("analyst", "analyst123")
        assert user is not None
        assert user["username"] == "analyst"

    def test_authenticate_auditor_success(self):
        """Should return user dict for valid auditor credentials."""
        user = authenticate_user("auditor", "auditor123")
        assert user is not None
        assert user["username"] == "auditor"

    def test_authenticate_wrong_password(self):
        """Should return None for wrong password."""
        result = authenticate_user("admin", "wrongpassword")
        assert result is None

    def test_authenticate_unknown_user(self):
        """Should return None for unknown username."""
        result = authenticate_user("nonexistent", "password")
        assert result is None

    def test_authenticate_empty_credentials(self):
        """Should return None for empty username."""
        result = authenticate_user("", "admin123")
        assert result is None

    def test_authenticate_empty_password(self):
        """Should return None for empty password."""
        result = authenticate_user("admin", "")
        assert result is None


class TestCreateAccessToken:
    """Tests for create_access_token function."""

    def test_returns_string(self):
        """Should return a non-empty string."""
        token = create_access_token({"sub": "admin", "roles": ["admin"]}, _SECRET, 60)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_is_valid_jwt(self):
        """Returned string should be a decodable JWT."""
        token = create_access_token({"sub": "admin"}, _SECRET, 60)
        payload = decode_token(token, _SECRET)
        assert payload is not None

    def test_token_contains_sub(self):
        """Token payload should contain the sub claim."""
        token = create_access_token({"sub": "admin"}, _SECRET, 60)
        payload = decode_token(token, _SECRET)
        assert payload["sub"] == "admin"

    def test_token_type_is_access(self):
        """Token payload should have type='access'."""
        token = create_access_token({"sub": "admin"}, _SECRET, 60)
        payload = decode_token(token, _SECRET)
        assert payload["type"] == "access"

    def test_token_has_exp_claim(self):
        """Token should have an exp claim."""
        token = create_access_token({"sub": "admin"}, _SECRET, 60)
        payload = decode_token(token, _SECRET)
        assert "exp" in payload

    def test_token_includes_custom_claims(self):
        """Custom claims should be present in decoded payload."""
        token = create_access_token({"sub": "admin", "roles": ["admin"], "org_id": 1}, _SECRET, 60)
        payload = decode_token(token, _SECRET)
        assert payload["roles"] == ["admin"]
        assert payload["org_id"] == 1


class TestCreateRefreshToken:
    """Tests for create_refresh_token function."""

    def test_returns_string(self):
        """Should return a non-empty string."""
        token = create_refresh_token({"sub": "admin"}, _SECRET, 7)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_type_is_refresh(self):
        """Refresh token should have type='refresh'."""
        token = create_refresh_token({"sub": "admin"}, _SECRET, 7)
        payload = decode_token(token, _SECRET)
        assert payload is not None
        assert payload["type"] == "refresh"

    def test_refresh_token_has_sub(self):
        """Refresh token should contain sub claim."""
        token = create_refresh_token({"sub": "analyst"}, _SECRET, 7)
        payload = decode_token(token, _SECRET)
        assert payload["sub"] == "analyst"

    def test_access_and_refresh_tokens_differ(self):
        """Access and refresh tokens for same data should be different strings."""
        data = {"sub": "admin"}
        access = create_access_token(data, _SECRET, 60)
        refresh = create_refresh_token(data, _SECRET, 7)
        assert access != refresh


class TestDecodeToken:
    """Tests for decode_token function."""

    def test_returns_none_for_invalid_token(self):
        """Should return None for an invalid token string."""
        result = decode_token("not.a.valid.token", _SECRET)
        assert result is None

    def test_returns_none_for_wrong_secret(self):
        """Should return None when token was signed with a different secret."""
        token = create_access_token({"sub": "admin"}, _SECRET, 60)
        result = decode_token(token, "wrong-secret")
        assert result is None

    def test_returns_none_for_expired_token(self):
        """Should return None for an expired token."""
        # Create a token that expires in -1 minutes (already expired)
        token = create_access_token({"sub": "admin"}, _SECRET, -1)
        result = decode_token(token, _SECRET)
        assert result is None

    def test_returns_none_for_empty_string(self):
        """Should return None for empty string."""
        result = decode_token("", _SECRET)
        assert result is None

    def test_decodes_valid_access_token(self):
        """Should return payload dict for a valid access token."""
        token = create_access_token({"sub": "admin", "roles": ["admin"]}, _SECRET, 60)
        payload = decode_token(token, _SECRET)
        assert payload is not None
        assert payload["sub"] == "admin"
        assert payload["type"] == "access"

    def test_decodes_valid_refresh_token(self):
        """Should return payload dict for a valid refresh token."""
        token = create_refresh_token({"sub": "analyst"}, _SECRET, 7)
        payload = decode_token(token, _SECRET)
        assert payload is not None
        assert payload["sub"] == "analyst"
        assert payload["type"] == "refresh"


class TestUserToResponse:
    """Tests for user_to_response function."""

    def test_excludes_password_hash(self):
        """Response should not include password_hash field."""
        user = DEMO_USERS["admin"]
        response = user_to_response(user)
        assert "password_hash" not in response

    def test_includes_username(self):
        """Response should include username."""
        user = DEMO_USERS["admin"]
        response = user_to_response(user)
        assert response["username"] == "admin"

    def test_includes_display_name(self):
        """Response should include display_name."""
        user = DEMO_USERS["analyst"]
        response = user_to_response(user)
        assert response["display_name"] == "数据分析师"

    def test_includes_roles(self):
        """Response should include roles."""
        user = DEMO_USERS["admin"]
        response = user_to_response(user)
        assert "roles" in response
        assert "admin" in response["roles"]

    def test_includes_org_id(self):
        """Response should include org_id."""
        user = DEMO_USERS["admin"]
        response = user_to_response(user)
        assert response["org_id"] == 1

    def test_original_user_unchanged(self):
        """user_to_response should not mutate the original user dict."""
        user = DEMO_USERS["admin"].copy()
        original_keys = set(user.keys())
        user_to_response(user)
        assert set(user.keys()) == original_keys
