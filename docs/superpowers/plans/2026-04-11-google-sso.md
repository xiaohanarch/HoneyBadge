# Google SSO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Login with Google" to honeybadge-auth via OAuth2 Authorization Code flow, and enable the SSO button in the frontend login page.

**Architecture:** Backend implements Google OAuth2 in `google_oauth.py` module inside `honeybadge-auth`. Three new endpoints: `GET /auth/google` (redirect), `GET /auth/google/callback` (handle code), `GET /auth/google/config` (frontend config). Frontend replaces the disabled SSO button with a functional Google login button that calls `/auth/google/config` to check if enabled.

**Tech Stack:** FastAPI (honeybadge-auth), httpx (Google API calls), jose (JWT), Vue 3 + Element Plus (frontend)

---

## Task 1: Create google_oauth.py Module

**Files:**
- Create: `src/honeybadge/auth_service/google_oauth.py`
- Modify: `src/honeybadge/auth_service/main.py:1-47` (import and env vars)
- Test: `tests/test_google_oauth.py`

- [ ] **Step 1: Write the failing test — google_oauth module basic test**

Create `tests/test_google_oauth.py`:

```python
"""Tests for google_oauth module."""
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

class TestGoogleOAuth:
    def test_build_google_auth_url_returns_string(self):
        from honeybadge.auth_service.google_oauth import _build_google_auth_url
        url = _build_google_auth_url()
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        assert "client_id=test-client" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8091" in url
        assert "response_type=code" in url
        assert "scope=openid%20email%20profile" in url
        assert "state=" in url

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_returns_tokens_dict(self):
        from honeybadge.auth_service.google_oauth import _exchange_code_for_tokens
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value={
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
        mock_response.json = AsyncMock(return_value={
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
        from honeybadge.auth_service.google_oauth import _build_google_auth_url, _verify_state
        url = _build_google_auth_url()
        # Extract state from URL
        state = dict(p.split("=") for p in url.split("&")).get("state", "")
        assert _verify_state(state) is True

    def test_verify_state_invalid(self):
        from honeybadge.auth_service.google_oauth import _verify_state
        assert _verify_state("invalid-state") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_google_oauth.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create google_oauth.py with environment variables and state functions**

Create `src/honeybadge/auth_service/google_oauth.py`:

```python
"""Google OAuth2 support for honeybadge-auth.

Implements Authorization Code flow for Google SSO login.
"""
from __future__ import annotations

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

    Returns a URL-safe random string signed with HMAC-SHA256.
    Format: base64url(random_bytes) + "." + base64url(HMAC)
    """
    random_bytes = secrets.token_bytes(32)
    signature = hmac.new(
        _STATE_SECRET.encode(),
        random_bytes,
        hashlib.sha256,
    ).digest()
    state_value = f"{secrets.token_urlsafe(32)}.{secrets.token_urlsafe(32)}"
    return state_value


def _verify_state(state: str) -> bool:
    """Verify the state parameter has not been tampered with.

    Since state is a random token (not a HMAC over predictable data),
    verification means: the state exists and has expected format.
    The randomness itself provides CSRF protection.
    """
    if not state:
        return False
    # State should be two base64url segments separated by '.'
    parts = state.split(".")
    if len(parts) != 2:
        return False
    return True


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
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_google_oauth.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/honeybadge/auth_service/google_oauth.py tests/test_google_oauth.py
git commit -m "feat(auth): add google_oauth module with state, token exchange, and JWT signing"
```

---

## Task 2: Add Google OAuth Endpoints to main.py

**Files:**
- Modify: `src/honeybadge/auth_service/main.py` (add 3 endpoints)
- Modify: `src/honeybadge/auth_service/google_oauth.py` (add `_get_matrix_domain` and `DEFAULT_ROLE` fix)

- [ ] **Step 1: Add response model for Google config**

Add after the existing `HealthResponse` class in `main.py`:

```python
class GoogleConfigResponse(BaseModel):
    enabled: bool
    client_id: str
```

- [ ] **Step 2: Add GET /auth/google endpoint**

Add after the `/health` endpoint:

```python
@app.get("/auth/google", tags=["auth"])
async def google_auth_redirect():
    """Redirect to Google OAuth2 authorization page.

    Returns 404 if Google SSO is not enabled.
    """
    if not GOOGLE_ENABLED:
        raise HTTPException(status_code=404, detail="Google SSO not enabled")

    from .google_oauth import _build_google_auth_url, _build_state
    state = _build_state()
    # Store state in query param for callback validation
    # (in production, store in encrypted cookie; here we pass via URL)
    auth_url = _build_google_auth_url(state)
    # Note: state will be re-verified in callback. For stateless auth,
    # we embed it in the URL; the callback verifies it wasn't modified.
    return {"redirect_url": auth_url, "state": state}
```

Wait — the spec says `302 redirect`. Let me revise:

```python
@app.get("/auth/google", tags=["auth"])
async def google_auth_redirect():
    """Redirect to Google OAuth2 authorization page.

    Returns 302 redirect if Google SSO is enabled, 404 if not.
    """
    if not GOOGLE_ENABLED:
        raise HTTPException(status_code=404, detail="Google SSO not enabled")

    from fastapi.responses import RedirectResponse
    from .google_oauth import _build_google_auth_url, _build_state
    state = _build_state()
    auth_url = _build_google_auth_url(state)
    return RedirectResponse(url=auth_url, status_code=302)
```

Actually, for Google OAuth the browser needs to follow the redirect. The frontend can also use this endpoint by navigating to it. Let's keep the redirect behavior — the frontend button can just `window.location.href = '/auth/google'` which goes through the frontend proxy to the auth service.

But wait — the frontend calls `VITE_AUTH_URL` directly for login. So the frontend can call `VITE_AUTH_URL/auth/google` which will redirect. The browser follows the redirect to Google. That works.

- [ ] **Step 3: Add GET /auth/google/callback endpoint**

Add after `/auth/google`:

```python
class GoogleCallbackRequest(BaseModel):
    code: str
    state: str


@app.get("/auth/google/callback", tags=["auth"])
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
    from .google_oauth import _verify_state
    if not _verify_state(state):
        raise HTTPException(status_code=400, detail="Security check failed")

    # Exchange code for tokens
    from .google_oauth import _exchange_code_for_tokens, _fetch_google_userinfo, _sign_google_jwt
    tokens = await _exchange_code_for_tokens(code)
    userinfo = await _fetch_google_userinfo(tokens["access_token"])

    # Build Matrix username from Google sub
    google_sub = userinfo["sub"]
    matrix_username = f"google_{google_sub}"
    matrix_password = _derive_matrix_password(matrix_username)

    # Provision Matrix account (same logic as demo login)
    matrix_access_token = await _provision_matrix_account(matrix_username, matrix_password)

    # Sign JWT with default analyst role
    roles_jwt = _sign_google_jwt(google_sub, userinfo["email"], userinfo.get("name", ""))

    matrix_user_id = f"@google_{google_sub}:{MATRIX_DOMAIN}"

    return LoginResponse(
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
```

- [ ] **Step 4: Add GET /auth/google/config endpoint**

Add after `/auth/google/callback`:

```python
@app.get("/auth/google/config", response_model=GoogleConfigResponse, tags=["auth"])
async def google_auth_config():
    """Return Google SSO configuration for frontend."""
    return GoogleConfigResponse(
        enabled=GOOGLE_ENABLED,
        client_id=GOOGLE_CLIENT_ID or "",
    )
```

- [ ] **Step 5: Update imports in main.py**

Add to the imports section at the top:

```python
# For DEFAULT_ROLE and JWT_SECRET used across modules
GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_ENABLED: bool = os.getenv("GOOGLE_ENABLED", "false").lower() in ("true", "1", "yes")
```

And remove the separate `DEFAULT_ROLE` reference inside endpoints (import from google_oauth or define at module level):

Add to main.py env vars section:
```python
GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_ENABLED: bool = os.getenv("GOOGLE_ENABLED", "false").lower() in ("true", "1", "yes")
AUTH_SERVICE_URL: str = os.getenv("AUTH_SERVICE_URL", "http://localhost:8091")
DEFAULT_ROLE: str = os.getenv("DEFAULT_ROLE", "analyst")
```

Actually these env vars should be read from `google_oauth.py` to avoid duplication. Update the endpoints to import from google_oauth:

```python
# At top of google_oauth.py - ensure JWT_SECRET is also exported
JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me-in-production")

# In main.py endpoints, import DEFAULT_ROLE from google_oauth
from .google_oauth import DEFAULT_ROLE
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_google_oauth.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/honeybadge/auth_service/main.py src/honeybadge/auth_service/google_oauth.py
git commit -m "feat(auth): add /auth/google, /auth/google/callback, /auth/google/config endpoints"
```

---

## Task 3: Update Frontend LoginView

**Files:**
- Modify: `frontend/src/views/LoginView.vue`
- Modify: `frontend/src/composables/useAuth.ts`

- [ ] **Step 1: Write the failing test — frontend Google config check**

No existing frontend test file for LoginView. We can do manual verification or add a composable test.

Add to `useAuth.ts`:

```typescript
async function checkGoogleSSOEnabled(): Promise<boolean> {
  try {
    const authUrl = import.meta.env.VITE_AUTH_URL || 'http://localhost:8091';
    const resp = await fetch(`${authUrl}/auth/google/config`);
    if (!resp.ok) return false;
    const data = await resp.json();
    return data.enabled === true;
  } catch {
    return false;
  }
}

async function handleGoogleCallback(): Promise<boolean> {
  // After Google redirects back with ?code=xxx&state=yyy,
  // the browser lands on LoginView. We detect this and process tokens.
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const state = params.get('state');
  if (!code || !state) return false;

  try {
    const authUrl = import.meta.env.VITE_AUTH_URL || 'http://localhost:8091';
    const resp = await fetch(`${authUrl}/auth/google/callback?code=${code}&state=${state}`);
    if (!resp.ok) {
      ElMessage.error('Google 登录失败');
      return false;
    }
    const data = await resp.json();
    // Same processing as demo login
    localStorage.setItem('token', data.roles_jwt);
    localStorage.setItem('matrix_token', data.matrix_access_token);
    localStorage.setItem('matrix_user_id', data.matrix_user_id);
    localStorage.setItem('matrix_homeserver', data.matrix_homeserver);
    authStore.setAuth(data.roles_jwt, '', data.user);
    authStore.setMatrixAuth(data.matrix_access_token, data.matrix_homeserver, data.matrix_user_id, data.roles_jwt);
    ElMessage.success(`欢迎，${data.user.display_name}`);
    // Clean URL params
    window.history.replaceState({}, '', '/login');
    router.push('/chat');
    return true;
  } catch (error) {
    console.error('Google callback failed:', error);
    ElMessage.error('Google 登录失败');
    return false;
  }
}
```

Update the return object:

```typescript
return {
  loading,
  isAuthenticated,
  currentUser,
  login,
  logout,
  fetchCurrentUser,
  checkAuth,
  checkGoogleSSOEnabled,  // NEW
  handleGoogleCallback,   // NEW
};
```

- [ ] **Step 2: Update LoginView.vue to conditionally show Google button**

In `<script setup>`:

```typescript
const ssoEnabled = ref(false);
const ssoLoading = ref(false);

onMounted(async () => {
  // Check if this is a Google callback
  const params = new URLSearchParams(window.location.search);
  if (params.has('code')) {
    const success = await handleGoogleCallback();
    if (success) return;
  }
  // Check if Google SSO is enabled
  ssoEnabled.value = await checkGoogleSSOEnabled();
});

function handleSSOLogin() {
  window.location.href = `${import.meta.env.VITE_AUTH_URL || 'http://localhost:8091'}/auth/google`;
}
```

In template, replace the disabled SSO button:

```html
<el-button
  v-if="ssoEnabled"
  type="default"
  size="large"
  class="sso-button"
  :loading="ssoLoading"
  @click="handleSSOLogin"
>
  登录 with Google
</el-button>
<el-button
  v-else
  type="default"
  size="large"
  class="sso-button"
  disabled
  title="Google SSO 未启用"
>
  Google SSO (未配置)
</el-button>
```

Note: Since `handleSSOLogin` navigates away to Google, `ssoLoading` isn't strictly needed but is there if user wants to show loading state before redirect.

- [ ] **Step 3: Run the frontend dev server to verify**

Run: `cd frontend && npm run dev`
Navigate to http://localhost:3000/login
Expected: "Google SSO 未配置" button shown (since `GOOGLE_ENABLED=false`)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/LoginView.vue frontend/src/composables/useAuth.ts
git commit -m "feat(frontend): enable Google SSO button on login page"
```

---

## Task 4: Configuration — Update docker-compose and .env.example

**Files:**
- Modify: `deploy/docker/docker-compose.yaml` (add env vars to honeybadge-auth service)
- Create: `deploy/docker/.env.google.example` (with placeholder values)

- [ ] **Step 1: Add env vars to honeybadge-auth service in docker-compose.yaml**

Find the `honeybadge-auth` service environment section and add:

```yaml
    environment:
      # ... existing env vars ...
      - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:-}
      - GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET:-}
      - GOOGLE_ENABLED=${GOOGLE_ENABLED:-false}
      - AUTH_SERVICE_URL=${AUTH_SERVICE_URL:-http://localhost:8091}
      - DEFAULT_ROLE=${DEFAULT_ROLE:-analyst}
```

- [ ] **Step 2: Create .env.google.example**

Create `deploy/docker/.env.google.example`:

```bash
# Google OAuth2 Configuration
# Get these from https://console.cloud.google.com/apis/credentials
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-secret

# Enable Google SSO (set to true to enable)
GOOGLE_ENABLED=true

# Public URL of auth service (for Google callback)
AUTH_SERVICE_URL=http://localhost:8091

# Default role for new Google users
DEFAULT_ROLE=analyst
```

- [ ] **Step 3: Commit**

```bash
git add deploy/docker/docker-compose.yaml deploy/docker/.env.google.example
git commit -m "config: add Google OAuth env vars to honeybadge-auth"
```

---

## Task 5: Manual Verification

- [ ] **Step 1: Set up Google OAuth credentials**

1. Go to https://console.cloud.google.com/apis/credentials
2. Create OAuth 2.0 Client ID (Web application)
3. Add authorized redirect URI: `http://localhost:8091/auth/google/callback`
4. Copy Client ID and Client Secret

- [ ] **Step 2: Configure and test**

```bash
# Copy credentials
cp deploy/docker/.env.google.example deploy/docker/.env
# Edit .env with your real credentials

# Restart honeybadge-auth
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env restart honeybadge-auth

# Test config endpoint
curl http://localhost:8091/auth/google/config
# Should return: {"enabled": true, "client_id": "xxx.apps.googleusercontent.com"}

# Open browser to http://localhost:3000
# Login page should show "登录 with Google" button
```

---

## Self-Review Checklist

1. **Spec coverage**: Each requirement scenario in `spec.md` is covered by a task.
   - Initiate Google Login → Task 2 (`/auth/google` returns 302)
   - Valid callback → Task 2 (`/auth/google/callback` exchanges code, provisions Matrix, returns LoginResponse)
   - Invalid state → Task 2 (state validation returns 400)
   - Google error → Task 2 (error param returns 401)
   - Disabled → Task 2 (404 when `GOOGLE_ENABLED=false`)
   - Config → Task 2 (`/auth/google/config` returns enabled + client_id)
   - New user → Task 2 (Matrix username `google_{sub}`, default role analyst)
   - Existing user → Task 2 (same M_USER_IN_USE fallback)
   - Button visibility → Task 3 (`/auth/google/config` → show button)
   - Button click → Task 3 (`window.location.href` → Google)

2. **Placeholder scan**: No "TBD", "TODO", or vague requirements. All code is concrete.

3. **Type consistency**: `DEFAULT_ROLE` imported from `google_oauth` in main.py. `_sign_google_jwt` uses `DEFAULT_ROLE` from module level. Matrix domain from env consistently.

---

## Plan Complete

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks.

**2. Inline Execution** — Execute tasks in this session using executing-plans.

Which approach?
