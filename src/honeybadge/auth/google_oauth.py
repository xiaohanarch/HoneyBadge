"""Google OAuth2 Integration for HoneyBadge SSO."""

from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class GoogleUserInfo:
    """Google user information."""

    sub: str  # Google user ID
    email: str
    name: str
    picture: Optional[str] = None


class GoogleOAuth2:
    """
    Google OAuth2 client for SSO integration.

    To set up:
    1. Go to https://console.cloud.google.com/apis/credentials
    2. Create an OAuth 2.0 Client ID (Web application)
    3. Set authorized redirect URIs to: {your_app_url}/auth/google/callback
    4. Copy Client ID and Client Secret to environment
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: list[str] = None,
    ):
        """
        Initialize Google OAuth2 client.

        Args:
            client_id: Google OAuth Client ID
            client_secret: Google OAuth Client Secret
            redirect_uri: Callback URL after authorization
            scopes: List of OAuth scopes (default: openid, email, profile)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes or ["openid", "email", "profile"]
        self._auth_base = "https://accounts.google.com/o/oauth2/v2/auth"
        self._token_url = "https://oauth2.googleapis.com/token"
        self._userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"

    def get_authorization_url(self, state: str = "") -> str:
        """
        Get the Google authorization URL.

        Args:
            state: State parameter for CSRF protection

        Returns:
            Authorization URL to redirect user to
        """
        import urllib.parse

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state

        return f"{self._auth_base}?{urllib.parse.urlencode(params)}"

    async def exchange_code_for_token(self, code: str) -> dict:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from callback

        Returns:
            Token response dict with access_token, refresh_token, etc.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_user_info(self, access_token: str) -> GoogleUserInfo:
        """
        Get user information from Google.

        Args:
            access_token: Access token from token exchange

        Returns:
            GoogleUserInfo with user details
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self._userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            data = response.json()

            return GoogleUserInfo(
                sub=data["sub"],
                email=data["email"],
                name=data.get("name", ""),
                picture=data.get("picture"),
            )

    async def refresh_access_token(self, refresh_token: str) -> dict:
        """
        Refresh an expired access token.

        Args:
            refresh_token: Refresh token

        Returns:
            New token response
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            return response.json()
