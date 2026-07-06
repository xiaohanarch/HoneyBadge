"""JWT authentication helpers for HoneyBadge server.

Provides demo users, password verification, and JWT token creation/decoding.

Demo credentials (for development/testing only):
  - admin             / admin123   (系统管理员,  roles=["admin"],   org_id=1000)
  - analyst           / analyst123 (数据分析师,  roles=["analyst"], org_id=1000)
  - auditor           / auditor123 (审计员,      roles=["auditor"], org_id=1000)
  - procurement_lead  / lead123    (采购部门领导, roles=["analyst"], org_id=1000)
  - subsidiary_lead   / lead123    (子公司领导,  roles=["analyst"], org_id=1021)

DEMO_USERS is loaded from a YAML file when ``HONEYBADGE_USERS_CONFIG``
points to one (see deploy/config/users.yaml); otherwise the built-in
defaults below are used. Plaintext passwords in the YAML are hashed with
bcrypt at load time.

In production, replace DEMO_USERS with a real user-store lookup and use
strong secrets loaded from environment variables via ServerConfig.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from jose import JWTError, jwt
from passlib.context import CryptContext

# ---------------------------------------------------------------------------
# Password hashing context (bcrypt)
# ---------------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# Default demo user store (used when HONEYBADGE_USERS_CONFIG is unset).
# Passwords are hashed at module load time so the plaintext never persists.
# ---------------------------------------------------------------------------

_DEFAULT_DEMO_USERS: dict[str, dict[str, Any]] = {
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


def _load_users_from_yaml(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load demo users from a YAML file, hashing plaintext passwords.

    The YAML schema mirrors deploy/config/users.yaml:
    ``users: <username>: { id, username, password, display_name, roles, org_id }``.

    The ``password`` field is plaintext in the YAML and hashed with bcrypt
    here so the returned dict matches the shape of the built-in defaults
    (``password_hash`` key, no plaintext retained).

    Args:
        path: Path to the YAML file.

    Returns:
        A dict mapping username to a user dict with ``password_hash``.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is malformed or missing required keys.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Users config file not found: {p}")

    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict) or "users" not in data:
        raise ValueError(f"Invalid users config {p}: missing top-level 'users' key")

    raw = data["users"]
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid users config {p}: 'users' must be a mapping")

    result: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid users config {p}: entry '{key}' must be a mapping")
        if "password" not in entry:
            raise ValueError(f"Invalid users config {p}: entry '{key}' missing 'password'")
        result[key] = {
            "id": entry.get("id", key),
            "username": entry.get("username", key),
            "password_hash": pwd_context.hash(entry["password"]),
            "display_name": entry.get("display_name", key),
            "roles": list(entry.get("roles", [])),
            "org_id": entry.get("org_id"),
        }

    return result


def load_demo_users() -> dict[str, dict[str, Any]]:
    """Load demo users from env-configured YAML, falling back to defaults.

    Reads ``HONEYBADGE_USERS_CONFIG`` for the YAML path. If unset or the
    file is missing/malformed, returns the built-in demo defaults.

    Returns:
        A dict mapping username to user dict (with ``password_hash``).
    """
    yaml_path = os.environ.get("HONEYBADGE_USERS_CONFIG")
    if not yaml_path:
        return {k: dict(v) for k, v in _DEFAULT_DEMO_USERS.items()}
    try:
        return _load_users_from_yaml(yaml_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[auth] WARNING: failed to load users from {yaml_path}: {exc}", file=sys.stderr)
        return {k: dict(v) for k, v in _DEFAULT_DEMO_USERS.items()}


# Module-level singleton — loaded once at import time. All existing imports
# (`from honeybadge.server.auth import DEMO_USERS`) continue to work unchanged.
DEMO_USERS: dict[str, dict[str, Any]] = load_demo_users()

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
    payload["jti"] = str(uuid.uuid4())
    payload["iat"] = int(datetime.now(tz=timezone.utc).timestamp())
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
    payload["jti"] = str(uuid.uuid4())
    payload["iat"] = int(datetime.now(tz=timezone.utc).timestamp())
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
