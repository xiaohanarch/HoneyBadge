"""HoneyBadge Auth Service.

Stateless microservice that:
1. Validates username/password against DEMO_USERS
2. Provisions per-user Matrix accounts in Tuwunel (HiClaw Manager)
3. Returns both a Matrix access token AND a roles JWT to the browser
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt
from pydantic import BaseModel

from honeybadge.server.auth import authenticate_user
from .google_oauth import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_ENABLED,
    AUTH_SERVICE_URL,
    DEFAULT_ROLE,
    GoogleOAuthError,
    _build_google_auth_url,
    _build_state,
    _exchange_code_for_tokens,
    _fetch_google_userinfo,
    _sign_google_jwt,
    _verify_state,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Environment configuration (with defaults)
# ---------------------------------------------------------------------------

TUWUNEL_URL: str = os.getenv("TUWUNEL_URL", "http://hiclaw-manager:6167")
MATRIX_DOMAIN: str = os.getenv("MATRIX_DOMAIN", "matrix-local.hiclaw.io")
HICLAW_REGISTRATION_TOKEN: str = os.getenv(
    "HICLAW_REGISTRATION_TOKEN", "honeybadge-reg-token"
)
MATRIX_USER_SECRET: str = os.getenv("MATRIX_USER_SECRET", "hb-user-secret-dev")
JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
MATRIX_HOMESERVER_PUBLIC: str = os.getenv(
    "MATRIX_HOMESERVER_PUBLIC", "http://localhost:6167"
)

_ALGORITHM = "HS256"

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HoneyBadge Auth Service",
    description="Stateless auth microservice: validates credentials, provisions Matrix accounts, issues JWTs.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: str
    username: str
    display_name: str
    roles: list[str]
    org_id: int


class LoginResponse(BaseModel):
    matrix_access_token: str
    matrix_homeserver: str
    matrix_user_id: str
    roles_jwt: str
    user: UserInfo


class HealthResponse(BaseModel):
    status: str
    service: str


class GoogleConfigResponse(BaseModel):
    enabled: bool
    client_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_matrix_password(username: str) -> str:
    """Derive a deterministic Matrix password for a given username.

    Uses HMAC-SHA256 keyed on MATRIX_USER_SECRET so the same username always
    produces the same Matrix password across service restarts.
    """
    return hmac.HMAC(
        MATRIX_USER_SECRET.encode(),
        username.encode(),
        hashlib.sha256,
    ).hexdigest()


async def _provision_matrix_account(username: str, password: str) -> str:
    """Register or login the Matrix account for `username`.

    Attempts registration first.  If Tuwunel returns M_USER_IN_USE the account
    already exists, so we fall back to password login.

    Returns:
        The Matrix access_token string.

    Raises:
        HTTPException 503 if Tuwunel is unreachable.
        HTTPException 502 if Tuwunel returns an unexpected error.
    """
    matrix_username = f"hb-{username}"
    matrix_user_id = f"@{matrix_username}:{MATRIX_DOMAIN}"

    register_url = f"{TUWUNEL_URL}/_matrix/client/v3/register"
    login_url = f"{TUWUNEL_URL}/_matrix/client/v3/login"

    register_payload: dict[str, Any] = {
        "username": matrix_username,
        "password": password,
        "auth": {
            "type": "m.login.registration_token",
            "token": HICLAW_REGISTRATION_TOKEN,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # --- Attempt registration ---
            logger.info(
                "matrix_register_attempt",
                matrix_user_id=matrix_user_id,
                tuwunel_url=TUWUNEL_URL,
            )
            reg_response = await client.post(register_url, json=register_payload)

            if reg_response.status_code in (200, 201):
                try:
                    data = reg_response.json()
                except ValueError:
                    logger.error(
                        "matrix_response_invalid_json",
                        status=reg_response.status_code,
                        body=reg_response.text[:200],
                    )
                    raise HTTPException(
                        status_code=502,
                        detail="Invalid response from Matrix homeserver",
                    )
                access_token: str = data["access_token"]
                logger.info(
                    "matrix_register_success",
                    matrix_user_id=matrix_user_id,
                )
                return access_token

            try:
                reg_data = reg_response.json()
            except ValueError:
                logger.error(
                    "matrix_response_invalid_json",
                    status=reg_response.status_code,
                    body=reg_response.text[:200],
                )
                raise HTTPException(
                    status_code=502,
                    detail="Invalid response from Matrix homeserver",
                )
            errcode = reg_data.get("errcode", "")

            if reg_response.status_code == 400 and errcode == "M_USER_IN_USE":
                # Account already exists — fall back to login
                logger.info(
                    "matrix_user_in_use_fallback_to_login",
                    matrix_user_id=matrix_user_id,
                )
                login_payload: dict[str, Any] = {
                    "type": "m.login.password",
                    "identifier": {
                        "type": "m.id.user",
                        "user": matrix_username,
                    },
                    "password": password,
                }
                login_response = await client.post(login_url, json=login_payload)

                if login_response.status_code == 200:
                    try:
                        login_data = login_response.json()
                    except ValueError:
                        logger.error(
                            "matrix_response_invalid_json",
                            status=login_response.status_code,
                            body=login_response.text[:200],
                        )
                        raise HTTPException(
                            status_code=502,
                            detail="Invalid response from Matrix homeserver",
                        )
                    access_token = login_data["access_token"]
                    logger.info(
                        "matrix_login_success",
                        matrix_user_id=matrix_user_id,
                    )
                    return access_token

                logger.error(
                    "matrix_login_failed",
                    matrix_user_id=matrix_user_id,
                    status_code=login_response.status_code,
                    body=login_response.text[:200],
                )
                raise HTTPException(
                    status_code=502,
                    detail="Matrix login failed after registration conflict",
                )

            # Unexpected registration error
            logger.error(
                "matrix_register_unexpected_error",
                matrix_user_id=matrix_user_id,
                status_code=reg_response.status_code,
                errcode=errcode,
                body=reg_response.text[:200],
            )
            raise HTTPException(
                status_code=502,
                detail=f"Matrix registration failed: {errcode or 'unknown error'}",
            )

    except httpx.ConnectError as exc:
        logger.error(
            "matrix_homeserver_unreachable",
            tuwunel_url=TUWUNEL_URL,
            error=str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail="Matrix homeserver unavailable",
        ) from exc
    except httpx.TimeoutException as exc:
        logger.error(
            "matrix_homeserver_timeout",
            tuwunel_url=TUWUNEL_URL,
            error=str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail="Matrix homeserver unavailable",
        ) from exc


def _sign_roles_jwt(user: dict[str, Any], username: str) -> str:
    """Sign and return a roles JWT for the given user."""
    payload: dict[str, Any] = {
        "sub": user["id"],
        "user_id": f"@hb-{username}:{MATRIX_DOMAIN}",
        "username": username,
        "roles": user["roles"],
        "org_id": user["org_id"],
        "iss": "honeybadge-auth",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=_ALGORITHM)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    """Authenticate user, provision Matrix account, and return tokens."""
    # Step 1: validate credentials
    user = authenticate_user(body.username, body.password)
    if user is None:
        logger.warning("login_invalid_credentials", username=body.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    logger.info("login_credentials_ok", username=body.username)

    # Step 2: derive Matrix password
    matrix_password = _derive_matrix_password(body.username)

    # Step 3: provision (register or login) the Matrix account
    matrix_access_token = await _provision_matrix_account(
        body.username, matrix_password
    )

    # Step 4: sign roles JWT
    roles_jwt = _sign_roles_jwt(user, body.username)

    matrix_user_id = f"@hb-{body.username}:{MATRIX_DOMAIN}"

    logger.info(
        "login_success",
        username=body.username,
        matrix_user_id=matrix_user_id,
    )

    return LoginResponse(
        matrix_access_token=matrix_access_token,
        matrix_homeserver=MATRIX_HOMESERVER_PUBLIC,
        matrix_user_id=matrix_user_id,
        roles_jwt=roles_jwt,
        user=UserInfo(
            id=user["id"],
            username=user["username"],
            display_name=user["display_name"],
            roles=user["roles"],
            org_id=user["org_id"],
        ),
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", service="honeybadge-auth")


@app.get("/auth/google", tags=["auth"])
async def google_auth_redirect():
    """Redirect to Google OAuth2 authorization page.

    Returns 302 redirect if Google SSO is enabled, 404 if not.
    """
    if not GOOGLE_ENABLED:
        raise HTTPException(status_code=404, detail="Google SSO not enabled")

    state = _build_state()
    auth_url = _build_google_auth_url(state)
    return RedirectResponse(url=auth_url, status_code=302)


@app.get("/auth/google/callback", response_model=LoginResponse, tags=["auth"])
async def google_auth_callback(code: str = None, state: str = None, error: str = None):
    """Handle Google OAuth2 callback.

    Validates state, exchanges code for tokens, fetches user info,
    provisions Matrix account, and returns JWT tokens.
    """
    # Handle error from Google (e.g., user denied)
    if error:
        raise HTTPException(status_code=401, detail="Authentication failed")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    # Validate state
    if not _verify_state(state):
        raise HTTPException(status_code=400, detail="Security check failed")

    # Exchange code for tokens
    try:
        tokens = await _exchange_code_for_tokens(code)
    except GoogleOAuthError as e:
        logger.error("google_token_exchange_failed", error=str(e))
        raise HTTPException(status_code=502, detail="Invalid token response from Google")

    if "access_token" not in tokens:
        raise HTTPException(status_code=502, detail="Invalid token response from Google")

    # Fetch user info
    try:
        userinfo = await _fetch_google_userinfo(tokens["access_token"])
    except GoogleOAuthError as e:
        logger.error("google_userinfo_fetch_failed", error=str(e))
        raise HTTPException(status_code=502, detail="Invalid userinfo from Google")

    if "sub" not in userinfo or "email" not in userinfo:
        raise HTTPException(status_code=502, detail="Invalid userinfo from Google")

    # Build Matrix username from Google sub
    google_sub = userinfo["sub"]
    matrix_username = f"google_{google_sub}"
    matrix_password = _derive_matrix_password(matrix_username)

    # Provision Matrix account (same logic as demo login)
    matrix_access_token = await _provision_matrix_account(matrix_username, matrix_password)

    # Sign JWT with default analyst role
    roles_jwt = _sign_google_jwt(google_sub, userinfo["email"], userinfo.get("name", ""))

    matrix_user_id = f"@google_{google_sub}:{MATRIX_DOMAIN}"

    # Redirect to frontend with tokens in URL fragment (not sent to server)
    login_response = LoginResponse(
        matrix_access_token=matrix_access_token,
        matrix_homeserver=MATRIX_HOMESERVER_PUBLIC,
        matrix_user_id=matrix_user_id,
        roles_jwt=roles_jwt,
        user=UserInfo(
            id=f"google:{google_sub}",
            username=matrix_username,
            display_name=userinfo.get("name", userinfo["email"]),
            roles=[DEFAULT_ROLE],
            org_id=1,
        ),
    )

    # Flatten nested user object for URL fragment encoding
    data = login_response.model_dump()
    flat_data = {
        "matrix_access_token": data["matrix_access_token"],
        "matrix_homeserver": data["matrix_homeserver"],
        "matrix_user_id": data["matrix_user_id"],
        "roles_jwt": data["roles_jwt"],
        "user_id": data["user"]["id"],
        "user_username": data["user"]["username"],
        "user_display_name": data["user"]["display_name"],
        "user_roles": ",".join(data["user"]["roles"]),
        "user_org_id": str(data["user"]["org_id"]),
    }
    fragment = urllib.parse.urlencode(flat_data)
    frontend_url = f"http://localhost:3000/login#{fragment}"
    return RedirectResponse(url=frontend_url, status_code=302)


@app.get("/auth/google/config", response_model=GoogleConfigResponse, tags=["auth"])
async def google_auth_config():
    """Return Google SSO configuration for frontend."""
    return GoogleConfigResponse(
        enabled=GOOGLE_ENABLED,
        client_id=GOOGLE_CLIENT_ID or "",
    )
