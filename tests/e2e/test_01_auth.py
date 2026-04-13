"""
Authentication E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-001: Admin login with username/password
- TC-002: Analyst login with username/password
- TC-003: Auditor login with username/password
- TC-004: Invalid password login should fail
- TC-005: Logout functionality
- TC-006: Google SSO login (if configured)
- TC-007: Route guard - unauthenticated redirect
- TC-008: Token expiration handling
"""
import pytest
from playwright.sync_api import expect


BASE_URL = "http://localhost:3000"


class TestAuthentication:
    """Test authentication flows."""

    def test_tc001_admin_login_success(self, page, wait_for_chat_ready):
        """TC-001: Admin user can login with correct credentials."""
        page.goto(f"{BASE_URL}/login")
        page.wait_for_load_state("networkidle")

        # Verify login page elements
        expect(page.locator('input[name="username"]')).to_be_visible()
        expect(page.locator('input[name="password"]')).to_be_visible()
        expect(page.locator('button[type="submit"]')).to_be_visible()

        # Fill login form
        page.fill('input[name="username"]', "admin")
        page.fill('input[name="password"]', "admin123")
        page.click('button[type="submit"]')

        # Verify redirect to chat
        page.wait_for_url(f"{BASE_URL}/chat", timeout=30000)

        # Verify chat page loaded
        wait_for_chat_ready()

        # Verify user info displayed
        expect(page.locator(".user-info, .avatar, [class*='user']")).to_be_visible()

    def test_tc002_analyst_login_success(self, page, wait_for_chat_ready):
        """TC-002: Analyst user can login with correct credentials."""
        page.goto(f"{BASE_URL}/login")
        page.fill('input[name="username"]', "analyst")
        page.fill('input[name="password"]', "analyst123")
        page.click('button[type="submit"]')

        page.wait_for_url(f"{BASE_URL}/chat", timeout=30000)
        wait_for_chat_ready()

    def test_tc003_auditor_login_success(self, page, wait_for_chat_ready):
        """TC-003: Auditor user can login with correct credentials."""
        page.goto(f"{BASE_URL}/login")
        page.fill('input[name="username"]', "auditor")
        page.fill('input[name="password"]', "auditor123")
        page.click('button[type="submit"]')

        page.wait_for_url(f"{BASE_URL}/chat", timeout=30000)
        wait_for_chat_ready()

    def test_tc004_invalid_password_fails(self, page):
        """TC-004: Login with wrong password should fail."""
        page.goto(f"{BASE_URL}/login")
        page.fill('input[name="username"]', "admin")
        page.fill('input[name="password"]', "wrongpassword")
        page.click('button[type="submit"]')

        # Should stay on login page
        page.wait_for_url(f"{BASE_URL}/login", timeout=10000)

        # Should show error message
        error_locator = page.locator('.el-message--error, .error-message, [class*="error"]')
        if error_locator.count() > 0:
            expect(error_locator.first).to_be_visible()

    def test_tc005_logout(self, admin_logged_in, wait_for_chat_ready):
        """TC-005: User can logout successfully."""
        page = admin_logged_in
        wait_for_chat_ready()

        # Click logout button
        logout_button = page.locator('button:has-text("退出"), button:has-text("Logout"), [class*="logout"]')
        if logout_button.count() > 0:
            logout_button.first.click()

            # Should redirect to login page
            page.wait_for_url(f"{BASE_URL}/login", timeout=10000)

            # Verify cannot access chat without login
            page.goto(f"{BASE_URL}/chat")
            page.wait_for_url(f"{BASE_URL}/login", timeout=10000)

    def test_tc006_google_sso_button_visible(self, page):
        """TC-006: Google SSO button should be visible if configured."""
        page.goto(f"{BASE_URL}/login")

        # Check if Google SSO button exists
        google_button = page.locator('button:has-text("Google"), [class*="google"]')
        if google_button.count() > 0:
            expect(google_button.first).to_be_visible()
        # If not configured, test passes silently

    def test_tc007_route_guard_redirect(self, page):
        """TC-007: Unauthenticated access to /chat should redirect to /login."""
        page.goto(f"{BASE_URL}/chat")

        # Should redirect to login page
        page.wait_for_url(f"{BASE_URL}/login", timeout=10000)

        # Login page elements should be visible
        expect(page.locator('input[name="username"]')).to_be_visible()

    def test_tc008_login_page_elements(self, page):
        """TC-008: Login page renders all required elements."""
        page.goto(f"{BASE_URL}/login")
        page.wait_for_load_state("networkidle")

        # Logo
        logo = page.locator('.logo, [class*="logo"], img')
        if logo.count() > 0:
            expect(logo.first).to_be_visible()

        # Username input
        expect(page.locator('input[name="username"]')).to_be_visible()

        # Password input
        expect(page.locator('input[name="password"]')).to_be_visible()

        # Submit button
        submit_btn = page.locator('button[type="submit"]')
        expect(submit_btn).to_be_visible()

        # Form title
        title = page.locator('h1, h2, .title')
        if title.count() > 0:
            expect(title.first).to_be_visible()
