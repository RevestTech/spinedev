"""GET /api/standards/control-packs* integration."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_control_packs_list_and_get(test_app, sqlite_db, auth_headers):
    from tron.infra.db.session import get_session

    async def _override_session():
        async with sqlite_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=test_app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=auth_headers,
        ) as client:
            r = await client.get("/api/standards/control-packs")
            assert r.status_code == 200
            data = r.json()
            ids = {x["id"] for x in data["items"]}
            assert "soc2_reference" in ids

            g = await client.get("/api/standards/control-packs/soc2_reference")
            assert g.status_code == 200
            assert g.json()["id"] == "soc2_reference"
    finally:
        test_app.dependency_overrides.clear()
