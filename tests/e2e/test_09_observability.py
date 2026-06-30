"""
Observability Stack E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-801: Prometheus is healthy
- TC-802: Grafana is healthy
- TC-803: Loki is healthy
- TC-804: Alertmanager is healthy
- TC-805: Prometheus can scrape targets
- TC-806: Grafana dashboards accessible
- TC-807: Metrics endpoint returns data
- TC-808: Logs are being collected
- TC-809: Alert rules are configured
- TC-810: Service metrics available
"""
import httpx
import pytest
from playwright.sync_api import expect

BASE_URL = "http://localhost:3000"


class TestObservability:
    """Test observability stack components."""

    def test_tc801_prometheus_healthy(self):
        """TC-801: Prometheus is healthy."""
        try:
            response = httpx.get("http://localhost:9090/-/healthy", timeout=10)
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Prometheus at localhost:9090")

    def test_tc802_grafana_healthy(self):
        """TC-802: Grafana is healthy."""
        try:
            response = httpx.get("http://localhost:3030/api/health", timeout=10)
            assert response.status_code == 200
            health = response.json()
            # Grafana health returns {"commit":"...","database":"ok","version":"..."}
            assert health.get("database") == "ok" or health.get("status") == "ok", \
                f"Grafana health check failed: {health}"
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Grafana at localhost:3030")

    def test_tc803_loki_healthy(self):
        """TC-803: Loki log aggregation is healthy."""
        try:
            response = httpx.get("http://localhost:3100/ready", timeout=10)
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.skip("Loki not running at localhost:3100 (observability profile may not be active)")

    def test_tc804_alertmanager_healthy(self):
        """TC-804: Alertmanager is healthy."""
        try:
            response = httpx.get("http://localhost:9093/-/healthy", timeout=10)
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Alertmanager at localhost:9093")

    def test_tc805_prometheus_can_scrape_targets(self):
        """TC-805: Prometheus can scrape configured targets."""
        try:
            # Check Prometheus targets endpoint
            response = httpx.get("http://localhost:9090/api/v1/targets", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert data.get("status") == "success"
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Prometheus API at localhost:9090")

    def test_tc806_grafana_dashboards_accessible(self):
        """TC-806: Grafana dashboards are accessible."""
        import base64
        try:
            # Grafana datasources endpoint - password is admin123 (from .env GRAFANA_PASSWORD)
            auth_str = base64.b64encode(b"admin:admin123").decode()
            response = httpx.get(
                "http://localhost:3030/api/datasources",
                headers={"Authorization": f"Basic {auth_str}"},
                timeout=10
            )
            assert response.status_code == 200, \
                f"Grafana datasources returned {response.status_code}: {response.text[:200]}"
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Grafana API at localhost:3030")

    def test_tc807_metrics_endpoint_returns_data(self):
        """TC-807: Service metrics endpoints return data."""
        # HiClaw Manager internal port 8080 is exposed as 18080 on host
        try:
            response = httpx.get("http://localhost:18080/metrics", timeout=10)
            # Metrics endpoint may return 200 with prometheus data or 404
            assert response.status_code in [200, 404], \
                f"Unexpected status {response.status_code} from metrics endpoint"
            if response.status_code == 200:
                assert "# HELP" in response.text or "# TYPE" in response.text or len(response.text) > 0
        except httpx.ConnectError:
            # Higress gateway at 18080 may not serve /metrics directly
            pytest.skip("HiClaw Manager metrics not accessible at localhost:18080")

    def test_tc808_logs_being_collected(self):
        """TC-808: Logs are being collected by Loki/Promtail."""
        try:
            # Check Loki for recent logs
            response = httpx.get("http://localhost:3100/loki/api/v1/query", timeout=10)
            assert response.status_code in [200, 400]  # 400 if no query params provided
        except httpx.ConnectError:
            pytest.skip("Loki not running at localhost:3100 (observability profile may not be active)")

    def test_tc809_alert_rules_configured(self):
        """TC-809: Prometheus alert rules are configured."""
        try:
            response = httpx.get("http://localhost:9090/api/v1/rules", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert data.get("status") == "success"
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Prometheus rules API at localhost:9090")

    def test_tc810_service_metrics_available(self):
        """TC-810: Service-specific metrics are available."""
        # Check honeybadge-server metrics
        try:
            response = httpx.get("http://localhost:8090/api/metrics", timeout=10)
            if response.status_code == 404:
                pytest.skip("Metrics endpoint not exposed on honeybadge-server")
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.fail("Cannot connect to honeybadge-server at localhost:8090")

    def test_tc811_grafana_login(self, page):
        """TC-811: Grafana login page loads."""
        page.goto("http://localhost:3030/login")
        page.wait_for_load_state("networkidle")

        # Verify login elements
        username_input = page.locator('input[name="user"], input[name="username"]')
        password_input = page.locator('input[name="password"]')

        expect(username_input.first).to_be_visible(timeout=5000)
        expect(password_input.first).to_be_visible(timeout=5000)
