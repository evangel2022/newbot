"""Integration tests for the loopback health endpoint."""

from __future__ import annotations

import httpx

from newbot.adapters.transports.http_ws import HealthServer


async def test_health_endpoint_reports_ok_and_rejects_unknown_paths() -> None:
    server = HealthServer(port=0)
    server.start()
    try:
        assert server.port > 0
        async with httpx.AsyncClient() as client:
            ok = await client.get(f"{server.url}/health")
            missing = await client.get(f"{server.url}/nope")
    finally:
        server.stop()

    assert ok.status_code == 200
    assert ok.json() == {"status": "ok"}
    assert missing.status_code == 404
