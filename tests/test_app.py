import asyncio

import httpx

from backend.app import create_app


def _get(path: str) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path)

    return asyncio.run(request())


def test_health_endpoint_reports_phase_one() -> None:
    response = _get("/health")
    assert response.status_code == 200
    assert response.json()["phase"] == "01"


def test_status_endpoint_is_phase_one_only() -> None:
    response = _get("/status")
    assert response.status_code == 200
    assert response.json()["implementation_scope"] == "phase_01_foundation"
