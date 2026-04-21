"""
Authentication E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-001: Parametrized login for all demo users (admin, analyst, auditor)
- TC-004: Invalid credentials rejected
- TC-005: Logout redirects to login and blocks /chat access
- TC-006: Google SSO button visible (if configured)
- TC-007: JWT token contains correct user data
- TC-008: Login page renders correctly
"""
import json
import os
import base64
import pytest
from playwright.sync_api import expect
from tests.e2e.selectors import (
    LOGIN_USERNAME, LOGIN_PASSWORD, LOGIN_BUTTON, LOGIN_CONTAINER,
    SSO_BUTTON, CHAT_HEADER, CHAT_TEXTAREA, USER_AVATAR, LOGOUT_ITEM,
    CONNECTION_TAG,
)


BASE_URL = os.getenv("BASE_URL", "http://localhost:3000")


class TestAuthentication:
    """Test user authentication flows."""

    @pytest.mark.parametrize("username,password", [
        ("admin", "admin123"),
        ("analyst", "analyst123"),
        ("auditor", "auditor123"),
    ])
    def test_tc001_login_success(self, browser, username, password):
        """TC-001/002/003: All demo users can login and reach chat page."""
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, locale="zh-CN")
        page = context.new_page()
        page.set_default_timeout(30000)
        try:
            page.goto(f"{BASE_URL}/login")
            page.wait_for_selector(LOGIN_BUTTON, timeout=15000)
            page.fill(LOGIN_USERNAME, username)
            page.fill(LOGIN_PASSWORD, password)
            page.click(LOGIN_BUTTON)
            page.wait_for_url(f"{BASE_URL}/chat", timeout=30000)

            # Verify we're on the chat page with functional UI
            expect(page.locator(CHAT_HEADER)).to_be_visible()
            expect(page.locator(CHAT_TEXTAREA)).to_be_visible()
            expect(page.locator(USER_AVATAR)).to_be_visible()
        finally:
            page.close()
            context.close()

    def test_tc004_invalid_credentials_rejected(self, page):
        """TC-004: Invalid password keeps user on login page."""
        page.goto(f"{BASE_URL}/login")
        page.wait_for_selector(LOGIN_BUTTON, timeout=15000)
        page.fill(LOGIN_USERNAME, "admin")
        page.fill(LOGIN_PASSWORD, "wrongpassword")
        page.click(LOGIN_BUTTON)

        page.wait_for_timeout(3000)

        # User should still be on login page (not redirected to chat)
        assert "/login" in page.url, f"Expected to stay on /login, but URL is {page.url}"

    def test_tc005_logout_redirects_to_login(self, admin_logged_in):
        """TC-005: Logout redirects to login and blocks /chat access."""
        page = admin_logged_in

        # Click user avatar to open the Element Plus dropdown
        page.locator(USER_AVATAR).click(force=True)

        # Element Plus v2 teleports the dropdown menu to <body> with position:fixed,
        # so offsetParent is always null — must wait with Playwright state check.
        logout_item = page.locator(LOGOUT_ITEM)
        logout_item.wait_for(state="visible", timeout=5000)
        logout_item.click()

        # Should be redirected to login
        page.wait_for_url(f"{BASE_URL}/login", timeout=15000)

        # Route guard: navigating to /chat should bounce back to /login
        page.goto(f"{BASE_URL}/chat")
        page.wait_for_url(f"{BASE_URL}/login", timeout=10000)

    def test_tc006_google_sso_button(self, page):
        """TC-006: Google SSO button visible if configured."""
        page.goto(f"{BASE_URL}/login")
        page.wait_for_selector(LOGIN_BUTTON, timeout=15000)

        sso_button = page.locator(SSO_BUTTON)
        # SSO may or may not be enabled; check based on env
        if sso_button.count() > 0:
            expect(sso_button).to_be_visible()
            sso_text = sso_button.inner_text()
            assert "Google" in sso_text, f"SSO button text should mention Google: '{sso_text}'"
        else:
            pytest.skip("SSO not configured in this environment")

    def test_tc007_jwt_token_after_login(self, admin_logged_in):
        """TC-007: JWT token in localStorage contains correct user info."""
        page = admin_logged_in

        # Extract token from localStorage
        token = page.evaluate("() => localStorage.getItem('roles_jwt') || localStorage.getItem('token') || ''")

        if not token:
            pytest.skip("No JWT token found in localStorage")

        # Decode JWT payload (base64 middle segment)
        parts = token.split(".")
        assert len(parts) == 3, f"JWT should have 3 parts, got {len(parts)}"

        # Decode payload with padding
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        assert "admin" in str(payload).lower(), f"JWT payload should reference admin: {payload}"

    def test_tc008_login_page_elements(self, page):
        """TC-008: Login page renders all expected elements."""
        page.goto(f"{BASE_URL}/login")
        page.wait_for_selector(LOGIN_BUTTON, timeout=15000)

        expect(page.locator(LOGIN_CONTAINER)).to_be_visible()
        expect(page.locator(LOGIN_USERNAME)).to_be_visible()
        expect(page.locator(LOGIN_PASSWORD)).to_be_visible()
        expect(page.locator(LOGIN_BUTTON)).to_be_visible()
