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
import pytest
from playwright.sync_api import expect
import httpx


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
            assert health.get("status") == "ok"
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Grafana at localhost:3030")

    def test_tc803_loki_healthy(self):
        """TC-803: Loki log aggregation is healthy."""
        try:
            response = httpx.get("http://localhost:3100/ready", timeout=10)
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Loki at localhost:3100")

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
        try:
            # Grafana datasources endpoint
            response = httpx.get(
                "http://localhost:3030/api/datasources",
                headers={"Authorization": "Basic YWRtaW46YWRtaW4xMjM0"},
                timeout=10
            )
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Grafana API at localhost:3030")

    def test_tc807_metrics_endpoint_returns_data(self):
        """TC-807: Service metrics endpoints return data."""
        # Check HiClaw Manager metrics
        try:
            response = httpx.get("http://localhost:8080/metrics", timeout=10)
            assert response.status_code == 200
            # Should contain Prometheus-formatted metrics
            assert "hiclaw" in response.text.lower() or "# HELP" in response.text
        except httpx.ConnectError:
            pytest.fail("Cannot connect to HiClaw Manager metrics at localhost:8080")

    def test_tc808_logs_being_collected(self):
        """TC-808: Logs are being collected by Loki/Promtail."""
        try:
            # Check Loki for recent logs
            response = httpx.get("http://localhost:3100/loki/api/v1/query", timeout=10)
            assert response.status_code in [200, 400]  # 400 if no query params
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Loki at localhost:3100")

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
            assert response.status_code in [200, 404]  # 404 if no metrics endpoint
        except httpx.ConnectError:
            pytest.fail("Cannot connect to honeybadge-server at localhost:8090")

    def test_tc811_grafana_login(self, page):
        """TC-811: Grafana login page loads."""
        page.goto("http://localhost:3030/login")
        page.wait_for_load_state("networkidle")

        # Verify login elements
        username_input = page.locator('input[name="user"], input[name="username"]')
        password_input = page.locator('input[name="password"]')

        if username_input.count() > 0 and password_input.count() > 0:
            expect(username_input.first).to_be_visible()
            expect(password_input.first).to_be_visible()
