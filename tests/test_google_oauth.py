"""Tests for google_oauth module."""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set environment variables before importing the module under test
os.environ["GOOGLE_CLIENT_ID"] = "test-client"
os.environ["AUTH_SERVICE_URL"] = "http://localhost:8091"
os.environ["STATE_SECRET"] = "test-state-secret-for-hmac"

class TestGoogleOAuth:
    def test_build_google_auth_url_returns_string(self):
        from honeybadge.auth_service.google_oauth import _build_google_auth_url
        url = _build_google_auth_url(state="test-state")
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        assert "client_id=test-client" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8091" in url
        assert "response_type=code" in url
        assert "scope=openid%20email%20profile" in url
        assert "state=test-state" in url

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_returns_tokens_dict(self):
        from honeybadge.auth_service.google_oauth import _exchange_code_for_tokens
        mock_response = MagicMock()
        mock_response.status_code = 200
        # httpx.Response.json() is synchronous, not async
        mock_response.json = MagicMock(return_value={
            "access_token": "test-access-token",
            "id_token": "test-id-token",
            "token_type": "Bearer"
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await _exchange_code_for_tokens("test-code")
            assert result["access_token"] == "test-access-token"
            assert result["id_token"] == "test-id-token"

    @pytest.mark.asyncio
    async def test_fetch_google_userinfo_returns_user_data(self):
        from honeybadge.auth_service.google_oauth import _fetch_google_userinfo
        mock_response = MagicMock()
        mock_response.status_code = 200
        # httpx.Response.json() is synchronous, not async
        mock_response.json = MagicMock(return_value={
            "sub": "123456789",
            "email": "testuser@gmail.com",
            "name": "Test User",
            "picture": "https://example.com/pic.jpg"
        })
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
            result = await _fetch_google_userinfo("test-access-token")
            assert result["sub"] == "123456789"
            assert result["email"] == "testuser@gmail.com"
            assert result["name"] == "Test User"

    def test_verify_state_valid(self):
        from honeybadge.auth_service.google_oauth import _build_state, _verify_state
        state = _build_state()
        assert _verify_state(state) is True

    def test_verify_state_invalid(self):
        from honeybadge.auth_service.google_oauth import _verify_state
        assert _verify_state("invalid-state") is False

    def test_verify_state_empty(self):
        from honeybadge.auth_service.google_oauth import _verify_state
        assert _verify_state("") is False
        assert _verify_state(None) is False

    def test_verify_state_wrong_parts(self):
        from honeybadge.auth_service.google_oauth import _verify_state
        assert _verify_state("singlepart") is False
        assert _verify_state("a.b.c") is False

    def test_verify_state_tampered_signature_rejected(self):
        """Verify that a state with tampered signature is rejected."""
        import os

        from honeybadge.auth_service.google_oauth import _build_state, _verify_state
        os.environ["STATE_SECRET"] = "test-secret"
        state = _build_state()
        # Tamper with the signature part
        parts = state.split(".")
        tampered = f"{parts[0]}.INVALID_SIGNATURE"
        assert _verify_state(tampered) is False

    def test_verify_state_wrong_secret_rejected(self):
        """Verify that a state built with different secret fails verification."""
        import os

        from honeybadge.auth_service.google_oauth import _build_state, _verify_state
        os.environ["STATE_SECRET"] = "secret-one"
        state = _build_state()
        # Change the secret
        os.environ["STATE_SECRET"] = "secret-two"
        assert _verify_state(state) is False

    def test_build_state_produces_hmac_signed_token(self):
        """Verify _build_state produces properly formatted HMAC-signed token."""
        import os

        from honeybadge.auth_service.google_oauth import _build_state, _verify_state
        os.environ["STATE_SECRET"] = "consistent-secret"
        state = _build_state()
        parts = state.split(".")
        assert len(parts) == 2
        # Both parts should be valid base64url (no padding needed for urlsafe)
        assert _verify_state(state) is True
