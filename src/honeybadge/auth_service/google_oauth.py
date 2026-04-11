"""Google OAuth2 support for honeybadge-auth.

Implements Authorization Code flow for Google SSO login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt

# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_ENABLED: bool = os.getenv("GOOGLE_ENABLED", "false").lower() in ("true", "1", "yes")
AUTH_SERVICE_URL: str = os.getenv("AUTH_SERVICE_URL", "http://localhost:8091")
DEFAULT_ROLE: str = os.getenv("DEFAULT_ROLE", "analyst")
JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_SCOPES = "openid email profile"

_STATE_SECRET = os.getenv("STATE_SECRET", "change-me-in-production")


def _build_state() -> str:
    """Build a signed state token for CSRF protection.

    Returns: base64url(random_bytes) + "." + base64url(HMAC-SHA256(random_bytes, STATE_SECRET))
    """
    random_bytes = secrets.token_bytes(32)
    signature = hmac.new(
        _STATE_SECRET.encode(),
        random_bytes,
        hashlib.sha256,
    ).digest()
    random_b64 = base64.urlsafe_b64encode(random_bytes).rstrip(b"=").decode()
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{random_b64}.{sig_b64}"


def _verify_state(state: str) -> bool:
    """Verify the state parameter HMAC signature."""
    if not state:
        return False
    parts = state.split(".")
    if len(parts) != 2:
        return False
    try:
        random_b64 = parts[0] + "=="
        sig_b64 = parts[1] + "=="
        random_bytes = base64.urlsafe_b64decode(random_b64)
        sig_bytes = base64.urlsafe_b64decode(sig_b64)
        expected_sig = hmac.new(_STATE_SECRET.encode(), random_bytes, hashlib.sha256).digest()
        return hmac.compare_digest(sig_bytes, expected_sig)
    except Exception:
        return False


def _build_google_auth_url(state: str) -> str:
    """Build the Google OAuth2 authorization URL.

    Args:
        state: Random state parameter for CSRF protection.

    Returns:
        Full Google OAuth2 authorization URL.
    """
    redirect_uri = f"{AUTH_SERVICE_URL}/auth/google/callback"
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "state": state,
        "prompt": "consent",  # force consent to get refresh token
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"


async def _exchange_code_for_tokens(code: str) -> dict[str, Any]:
    """Exchange authorization code for Google tokens.

    Args:
        code: Authorization code from Google callback.

    Returns:
        Dict with access_token, id_token, etc.

    Raises:
        HTTPException on failure.
    """
    redirect_uri = f"{AUTH_SERVICE_URL}/auth/google/callback"
    payload = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data=payload)
        if resp.status_code != 200:
            raise Exception(f"Token exchange failed: {resp.status_code} {resp.text}")
        return resp.json()


async def _fetch_google_userinfo(access_token: str) -> dict[str, Any]:
    """Fetch user info from Google.

    Args:
        access_token: Google access token.

    Returns:
        Dict with sub, email, name, picture.
    """
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            raise Exception(f"Userinfo fetch failed: {resp.status_code}")
        return resp.json()


def _sign_google_jwt(google_sub: str, email: str, display_name: str) -> str:
    """Sign a roles JWT for a Google-authenticated user.

    All Google users get the same default role.

    Args:
        google_sub: Google subject (unique user ID)
        email: Google email
        display_name: Google display name

    Returns:
        Encoded JWT string.
    """
    payload = {
        "sub": f"google:{google_sub}",
        "user_id": f"@google_{google_sub}:{_get_matrix_domain()}",
        "username": f"google_{google_sub}",
        "email": email,
        "display_name": display_name,
        "roles": [DEFAULT_ROLE],
        "org_id": 1,
        "iss": "honeybadge-auth",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=480),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _get_matrix_domain() -> str:
    """Get Matrix domain from environment or default."""
    return os.getenv("MATRIX_DOMAIN", "matrix-local.hiclaw.io")
