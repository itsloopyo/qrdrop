"""Tests for the health endpoint."""

from starlette.testclient import TestClient


class TestHealth:
    def test_health_endpoint_returns_healthy(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "healthy"}

    def test_health_does_not_require_auth(self, client: TestClient) -> None:
        # No login performed - still 200
        r = client.get("/health")
        assert r.status_code == 200
