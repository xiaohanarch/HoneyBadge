"""JWT authentication helpers for HoneyBadge server.

Provides demo users, password verification, and JWT token creation/decoding.

Demo credentials (for development/testing only):
  - admin             / admin123   (系统管理员,  roles=["admin"],   org_id=1000)
  - analyst           / analyst123 (数据分析师,  roles=["analyst"], org_id=1000)
  - auditor           / auditor123 (审计员,      roles=["auditor"], org_id=1000)
  - procurement_lead  / lead123    (采购部门领导, roles=["analyst"], org_id=1000)
  - subsidiary_lead   / lead123    (子公司领导,  roles=["analyst"], org_id=1021)

In production, replace DEMO_USERS with a real user-store lookup and use
strong secrets loaded from environment variables via ServerConfig.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

# ---------------------------------------------------------------------------
# Password hashing context (bcrypt)
# ---------------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# Demo user store
# Passwords are hashed at module load time so the plaintext never persists.
# ---------------------------------------------------------------------------

DEMO_USERS: dict[str, dict[str, Any]] = {
    "admin": {
        "id": "admin",
        "username": "admin",
        "password_hash": pwd_context.hash("admin123"),
        "display_name": "系统管理员",
        "roles": ["admin"],
        "org_id": 1000,
    },
    "analyst": {
        "id": "analyst",
        "username": "analyst",
        "password_hash": pwd_context.hash("analyst123"),
        "display_name": "数据分析师",
        "roles": ["analyst"],
        "org_id": 1000,
    },
    "auditor": {
        "id": "auditor",
        "username": "auditor",
        "password_hash": pwd_context.hash("auditor123"),
        "display_name": "审计员",
        "roles": ["auditor"],
        "org_id": 1000,
    },
    "procurement_lead": {
        "id": "procurement_lead",
        "username": "procurement_lead",
        "password_hash": pwd_context.hash("lead123"),
        "display_name": "采购部门领导",
        "roles": ["analyst"],
        "org_id": 1000,
    },
    "subsidiary_lead": {
        "id": "subsidiary_lead",
        "username": "subsidiary_lead",
        "password_hash": pwd_context.hash("lead123"),
        "display_name": "子公司领导",
        "roles": ["analyst"],
        "org_id": 1021,
    },
}

# JWT algorithm
_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    """Verify username and password against the demo user store.

    Args:
        username: The username to look up.
        password: The plaintext password to verify.

    Returns:
        The user dict if credentials are valid, otherwise None.
    """
    if not username or not password:
        return None
    user = DEMO_USERS.get(username)
    if user is None:
        return None
    if not pwd_context.verify(password, user["password_hash"]):
        return None
    return user


def create_access_token(data: dict[str, Any], secret: str, expire_minutes: int) -> str:
    """Create a signed JWT access token.

    Args:
        data:           Claims to embed (e.g. {"sub": "admin", "roles": [...]}).
        secret:         HMAC signing secret.
        expire_minutes: Token lifetime in minutes.

    Returns:
        Encoded JWT string.
    """
    payload = dict(data)
    payload["type"] = "access"
    payload["exp"] = datetime.now(tz=timezone.utc) + timedelta(minutes=expire_minutes)
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)  # type: ignore[no-any-return]


def create_refresh_token(data: dict[str, Any], secret: str, expire_days: int) -> str:
    """Create a signed JWT refresh token.

    Args:
        data:        Claims to embed (e.g. {"sub": "admin"}).
        secret:      HMAC signing secret.
        expire_days: Token lifetime in days.

    Returns:
        Encoded JWT string.
    """
    payload = dict(data)
    payload["type"] = "refresh"
    payload["exp"] = datetime.now(tz=timezone.utc) + timedelta(days=expire_days)
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)  # type: ignore[no-any-return]


def decode_token(token: str, secret: str) -> dict[str, Any] | None:
    """Decode and verify a JWT token.

    Returns None on any error: expired, invalid signature, malformed, etc.

    Args:
        token:  Encoded JWT string.
        secret: HMAC signing secret used when the token was created.

    Returns:
        Decoded payload dict, or None if the token is invalid.
    """
    if not token:
        return None
    try:
        payload: dict[str, Any] = jwt.decode(token, secret, algorithms=[_ALGORITHM])
        return payload
    except JWTError:
        return None


def user_to_response(user: dict[str, Any]) -> dict[str, Any]:
    """Convert a user dict to a safe API response (excludes password_hash).

    Args:
        user: A user dict from DEMO_USERS (or equivalent).

    Returns:
        A copy of the user dict without the ``password_hash`` field.
    """
    return {k: v for k, v in user.items() if k != "password_hash"}
