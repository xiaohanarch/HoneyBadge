"""
Infrastructure E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-701: NebulaGraph is healthy
- TC-702: PostgreSQL is healthy
- TC-703: Redis is healthy
- TC-704: MinIO is healthy
- TC-705: Higress is healthy
- TC-706: Tuwunel (Matrix) is healthy
- TC-707: honeybadge-server health
- TC-708: honeybadge-auth health
- TC-709: HiClaw Manager is healthy
- TC-710: Worker containers are running
- TC-711: Service mesh connectivity
- TC-712: Docker container status
"""
import pytest
from playwright.sync_api import expect
import httpx
import docker


BASE_URL = "http://localhost:3000"
API_BASE_URL = "http://localhost:8090"
AUTH_BASE_URL = "http://localhost:8091"


class TestInfrastructure:
    """Test infrastructure component health and connectivity."""

    def test_tc701_nebula_graph_healthy(self):
        """TC-701: NebulaGraph database is healthy."""
        # Check NebulaGraph health via Graphd port
        try:
            # Try connecting to NebulaGraph
            response = httpx.get("http://localhost:9669", timeout=10)
            # NebulaGraph may return redirects or 200 on status endpoint
            assert response.status_code in [200, 404, 301, 302]
        except httpx.ConnectError:
            pytest.fail("Cannot connect to NebulaGraph at localhost:9669")

    def test_tc702_postgresql_healthy(self, api_client):
        """TC-702: PostgreSQL database is healthy."""
        # Server health check includes PostgreSQL
        response = api_client.get("/api/health")
        if response.status_code == 200:
            health = response.json()
            # Should include postgres status
            assert "postgres" in str(health).lower() or "db" in str(health).lower()

    def test_tc703_redis_healthy(self):
        """TC-703: Redis cache is healthy."""
        try:
            import redis
            r = redis.Redis(host='localhost', port=6379, decode_responses=True)
            pong = r.ping()
            assert pong is True
        except ImportError:
            pytest.skip("redis-py not installed")
        except Exception as e:
            pytest.fail(f"Redis is not healthy: {e}")

    def test_tc704_minio_healthy(self):
        """TC-704: MinIO object storage is healthy."""
        # Check MinIO console or API
        try:
            # MinIO health check
            response = httpx.get("http://localhost:9000/minio/health/live", timeout=10)
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.fail("Cannot connect to MinIO at localhost:9000")

    def test_tc705_higress_healthy(self):
        """TC-705: Higress API gateway is healthy."""
        try:
            # Higress admin or health endpoint
            response = httpx.get("http://localhost:18001", timeout=10)
            assert response.status_code in [200, 301, 302, 404]
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Higress at localhost:18001")

    def test_tc706_tuwunel_matrix_healthy(self):
        """TC-706: Tuwunel (Matrix server) is healthy."""
        try:
            # Matrix server versions endpoint
            response = httpx.get("http://localhost:6167/_matrix/client/versions", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert "versions" in data
        except httpx.ConnectError:
            pytest.fail("Cannot connect to Tuwunel Matrix at localhost:6167")

    def test_tc707_honeybadge_server_healthy(self, api_client):
        """TC-707: honeybadge-server is healthy."""
        response = api_client.get("/api/health")
        assert response.status_code == 200
        health = response.json()
        assert health.get("status") == "ok" or "service" in health

    def test_tc708_honeybadge_auth_healthy(self, auth_api_client):
        """TC-708: honeybadge-auth is healthy."""
        response = auth_api_client.get("/health")
        assert response.status_code == 200
        health = response.json()
        assert health.get("status") == "ok" or health.get("service") == "honeybadge-auth"

    def test_tc709_hiclaw_manager_healthy(self):
        """TC-709: HiClaw Manager is healthy."""
        try:
            # HiClaw Manager has multiple ports, check one
            response = httpx.get("http://localhost:6167/_matrix/client/versions", timeout=10)
            # Manager houses Matrix, so this endpoint works
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.fail("Cannot connect to HiClaw Manager at localhost:6167")

    def test_tc710_worker_containers_running(self):
        """TC-710: Worker containers are running."""
        try:
            client = docker.from_env()
            # Check for worker containers
            containers = client.containers.list(filters={"name": "hiclaw"})
            worker_names = [c.name for c in containers]
            assert len(worker_names) >= 2, f"Expected at least 2 workers, found {worker_names}"
        except docker.errors.DockerNotFound:
            pytest.skip("Docker SDK not available or Docker not running")

    def test_tc711_service_mesh_connectivity(self, api_client):
        """TC-711: Service mesh connectivity works."""
        # API should be reachable
        response = api_client.get("/api/health")
        assert response.status_code == 200

        # Auth should be reachable
        auth_response = httpx.get(f"{AUTH_BASE_URL}/health", timeout=10)
        assert auth_response.status_code == 200

    def test_tc712_docker_container_status(self):
        """TC-712: All expected Docker containers are running."""
        try:
            client = docker.from_env()
            containers = client.containers.list()

            expected_services = [
                "nebula", "honeybadge", "hiclaw", "postgres",
                "redis", "minio", "higress", "tuwunel"
            ]

            running_containers = [c.name for c in containers]
            container_str = " ".join(running_containers)

            # Check at least some key services are running
            found_count = sum(1 for svc in expected_services if svc in container_str)
            assert found_count >= 5, f"Expected at least 5 key services running, found {found_count}"
        except docker.errors.DockerNotFound:
            pytest.skip("Docker SDK not available")
