import pytest
from httpx import ASGITransport, AsyncClient
from app import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_and_get_task(client):
    resp = await client.post("/api/tasks", json={
        "name": "Test Task", "url": "http://example.com",
        "config": {"concurrency": 3}
    })
    assert resp.status_code == 200
    task = resp.json()["task"]
    assert task["name"] == "Test Task"
    assert task["status"] == "pending"

    resp = await client.get(f"/api/tasks/{task['id']}")
    assert resp.status_code == 200
    assert resp.json()["task"]["name"] == "Test Task"


@pytest.mark.asyncio
async def test_list_tasks(client):
    resp = await client.get("/api/tasks")
    assert resp.status_code == 200
    assert "tasks" in resp.json()


@pytest.mark.asyncio
async def test_delete_task(client):
    resp = await client.post("/api/tasks", json={"name": "Del", "url": "http://x.com"})
    task_id = resp.json()["task"]["id"]
    resp = await client.delete(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    resp = await client.get(f"/api/tasks/{task_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_settings(client):
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    assert "settings" in resp.json()

    resp = await client.put("/api/settings", json={"test_key": "test_val"})
    assert resp.status_code == 200
    assert resp.json()["settings"]["test_key"] == "test_val"


@pytest.mark.asyncio
async def test_webui_served(client):
    resp = await client.get("/webui/index.html")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_task_lifecycle(client):
    resp = await client.post("/api/tasks", json={"name": "LC", "url": "http://example.com"})
    task_id = resp.json()["task"]["id"]

    resp = await client.post(f"/api/tasks/{task_id}/start")
    assert resp.status_code == 200

    resp = await client.post(f"/api/tasks/{task_id}/pause")
    assert resp.status_code == 200

    resp = await client.post(f"/api/tasks/{task_id}/resume")
    assert resp.status_code == 200
