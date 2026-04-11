# Google SSO Integration Design

## Overview

Add "Login with Google" as an alternative authentication method to `honeybadge-auth`, allowing users to sign in with their Google account. This is a demo to prove HoneyBadge can integrate with enterprise SSO providers.

## Goals

- Users can authenticate via Google OAuth2 instead of demo credentials
- New Google users get auto-provisioned Matrix account (same as demo login flow)
- All Google users start with the same default role (`analyst`)
- No PostgreSQL changes — JWT Claims are sufficient for this demo
- Keep `honeybadge-auth` stateless

## Non-Goals

- User management UI or database persistence
- Role mapping from Google groups/emails (Phase 2)
- Other SSO providers (extensible pattern, not added now)

## Architecture

```
Browser                     honeybadge-auth                    Google
  │                              │                              │
  │ GET /auth/google             │                              │
  │ ───────────────────────────► │                              │
  │                              │ 302 https://accounts.google.com/... │
  │ ◄─────────────────────────── │ ─────────────────────────────────►
  │                              │                              │
  │   (user logs in at Google)   │                              │
  │                              │                              │
  │ GET /auth/google/callback?code=xxx                          |
  │ ◄─────────────────────────── │ ◄─────── authorize + code ────
  │                              │                              |
  │                              │ POST https://oauth2.googleapis.com/token
  │                              │ ──────────────────────────────────►
  │                              │ ◄────── { access_token, id_token }
  │                              │                              |
  │                              │ GET https://www.googleapis.com/oauth2/v3/userinfo
  │                              │ ──────────────────────────────────►
  │                              │ ◄────── { email, name, sub }
  │                              |
  │                              │ _provision_matrix_account() — same as demo login
  │                              │ _sign_roles_jwt() — default role: analyst
  │                              |
  │ { matrix_access_token, roles_jwt, ... }                      |
  │ ◄─────────────────────────── │
```

## New Endpoints

### GET /auth/google

Redirects to Google OAuth2 authorization page.

**Query params**: none (uses session or state param for CSRF)

**Response**: 302 redirect to Google

```
https://accounts.google.com/o/oauth2/v2/auth?
  client_id={GOOGLE_CLIENT_ID}
  &redirect_uri={AUTH_SERVICE_URL}/auth/google/callback
  &response_type=code
  &scope=openid%20email%20profile
  &access_type=offline
  &state={csrf_token}
```

### GET /auth/google/callback

Handles Google OAuth2 callback with authorization code.

**Query params**:
- `code` — authorization code from Google
- `state` — CSRF token to validate

**Response** (same shape as `/login`):

```json
{
  "matrix_access_token": "...",
  "matrix_homeserver": "http://localhost:6167",
  "matrix_user_id": "@hb-user123:matrix-local.hiclaw.io",
  "roles_jwt": "...",
  "user": {
    "id": "google:{google_sub}",
    "username": "user123",
    "display_name": "User Name",
    "roles": ["analyst"],
    "org_id": 1
  }
}
```

**Error cases**:
- Missing/invalid `state` → 400
- Google returns error (e.g., user denied) → 401
- Token exchange fails → 502
- Matrix provisioning fails → 502/503

### GET /auth/google/config

Returns Google OAuth configuration for frontend.

**Response**:
```json
{
  "enabled": true,
  "client_id": "xxx.apps.googleusercontent.com"
}
```

Frontend uses this to show/hide the "Login with Google" button.

## Data Flow

1. User clicks "Login with Google" button in frontend
2. Frontend calls `GET /auth/google` → receives redirect to Google
3. User authenticates with Google and grants permission
4. Google redirects to `/auth/google/callback?code=xxx&state=yyy`
5. `honeybadge-auth` validates state, exchanges code for tokens
6. `honeybadge-auth` fetches user info from Google userinfo endpoint
7. `honeybadge-auth` provisions Matrix account (same `_provision_matrix_account` logic)
8. `honeybadge-auth` signs JWT with default role `analyst`
9. Returns same `LoginResponse` shape as `/login`
10. Frontend proceeds identically to demo login flow

## Configuration

Environment variables in `honeybadge-auth`:

| Variable | Description | Example |
|----------|-------------|---------|
| `GOOGLE_CLIENT_ID` | Google OAuth2 Client ID | `123.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 Client Secret | `GOCSPX-xxx` |
| `GOOGLE_ENABLED` | Enable Google SSO (default: false) | `true` |
| `AUTH_SERVICE_URL` | Public URL of auth service (for callback) | `http://localhost:8091` |
| `DEFAULT_ROLE` | Role for new Google users | `analyst` |

## Security

- **CSRF protection**: `state` parameter contains HMAC-signed random token
- **Redirect URI validation**: Must match configured `GOOGLE_REDIRECT_URI`
- **ID token validation**: Verify `aud` (audience) matches `GOOGLE_CLIENT_ID`
- **Scope**: `openid email profile` — no additional Google permissions needed

## Changes to Existing Code

### honeybadge-auth service

- Add new file `src/honeybadge/auth_service/google_oauth.py` — Google OAuth2 client
- Add new endpoints to `src/honeybadge/auth_service/main.py`
- No changes to `DEMO_USERS` or existing `/login` flow
- No database changes

### Frontend

- Add "Login with Google" button on login page
- Call `/auth/google` (redirect flow) or `/auth/google/config` to check if enabled
- Handle callback — but callback URL can be the same page, which reads tokens from URL fragment or redirects to Matrix SDK init

## Error Handling

| Error | User sees |
|-------|-----------|
| User denies Google permission | "Authentication failed. Please try again." |
| Invalid CSRF state | "Security check failed. Please try again." |
| Google API unavailable | "Google authentication is temporarily unavailable." |
| Matrix provisioning fails | "Failed to set up your account. Please contact admin." |

## Testing

- Manual: Click "Login with Google" → complete auth flow → verify chat works
- Unit test: `test_google_oauth.py` — mock Google APIs, verify token exchange and JWT creation
- Integration test: Full flow with real Google credentials (CI secrets needed)
