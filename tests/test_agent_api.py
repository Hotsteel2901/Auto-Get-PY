"""The agent integration surface.

Every supported tool reaches the same handlers through its own URL alias, so
these tests assert both that each alias resolves *and* that the payloads an
agent consumes are shaped correctly.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from api.agent_registry import AGENTS, all_aliases
from app import app

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           timeout=30) as async_client:
        yield async_client


# ── Aliases ─────────────────────────────────────────────────────────────────


async def test_every_registered_alias_serves_the_api(client):
    aliases = all_aliases()
    assert "/api/agent" in aliases
    # The tools the user asked for explicitly.
    assert {"/api/hermes", "/api/opencode", "/api/dsh", "/api/codex",
            "/api/claude"} <= set(aliases)

    for alias in aliases:
        resp = await client.get(f"{alias}/health")
        assert resp.status_code == 200, f"{alias}/health returned {resp.status_code}"
        assert resp.json()["service"] == "auto-get-py"


async def test_every_agent_in_the_registry_has_a_working_alias(client):
    for agent in AGENTS:
        resp = await client.get(f"{agent.primary_prefix}/manifest")
        assert resp.status_code == 200, f"{agent.id} alias is broken"
        assert resp.json()["canonical_prefix"] == "/api/agent"


async def test_canonical_prefix_is_in_the_openapi_schema(client):
    schema = (await client.get("/openapi.json")).json()
    paths = schema["paths"]
    assert "/api/agent/scrape" in paths
    assert "/api/agent/quick" in paths
    assert "/api/agent/fetch" in paths
    # Aliases stay out of the schema so the docs are not 17x duplicated.
    assert "/api/codex/scrape" not in paths
    assert not any(path.startswith("/api/dsh/") for path in paths)


# ── Discovery documents ─────────────────────────────────────────────────────


async def test_manifest_describes_the_service(client):
    body = (await client.get("/api/agent/manifest")).json()
    assert body["service"] == "Auto-Get-PY"
    assert body["canonical_prefix"] == "/api/agent"
    assert len(body["aliases"]) == len(all_aliases())
    assert "hls-merge" in body["capabilities"]
    assert body["openapi_url"] == "/openapi.json"

    endpoints = {e["path"] for e in body["endpoints"]}
    assert {"/scrape", "/quick", "/direct", "/fetch", "/status/{task_id}",
            "/results/{task_id}", "/cancel/{task_id}"} <= endpoints


async def test_agents_listing(client):
    body = (await client.get("/api/agent/agents")).json()
    ids = {agent["id"] for agent in body["agents"]}
    assert {"opencode", "dsh", "codex", "claude", "cursor", "gemini"} <= ids
    for agent in body["agents"]:
        assert agent["api_prefix"].startswith("/api/")
        assert isinstance(agent["config_files"], list)


async def test_agent_detail_and_404(client):
    ok = await client.get("/api/agent/agents/opencode")
    assert ok.status_code == 200
    assert ok.json()["id"] == "opencode"

    # Also resolvable by alias.
    by_alias = await client.get("/api/agent/agents/api/dsh")
    assert by_alias.status_code == 200
    assert by_alias.json()["id"] == "dsh"

    assert (await client.get("/api/agent/agents/nope")).status_code == 404


async def test_skill_document_is_markdown_with_front_matter(client):
    resp = await client.get("/api/agent/skill?agent=codex")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    body = resp.text
    assert body.startswith("---")
    assert "name: auto-get-py" in body
    assert "爬取" in body, "Chinese trigger words are missing from the front matter"
    assert "/api/codex" in body, "the skill does not mention this agent's alias"
    assert "/scrape" in body and "/quick" in body

    as_json = (await client.get("/api/agent/skill?agent=codex&format=json")).json()
    assert as_json["agent"] == "codex"
    assert "markdown" in as_json


async def test_skill_falls_back_to_generic_for_an_unknown_agent(client):
    resp = await client.get("/api/agent/skill?agent=not-a-real-tool")
    assert resp.status_code == 200
    assert "/api/agent" in resp.text


async def test_per_agent_reference_document(client):
    resp = await client.get("/api/agent/docs/opencode")
    assert resp.status_code == 200
    assert "opencode" in resp.text.lower()
    assert (await client.get("/api/agent/docs/nope")).status_code == 404


# ── Scraping through the agent API ──────────────────────────────────────────


async def test_quick_scrape_returns_urls_without_writing_files(client, local_site):
    before = (await client.get("/api/agent/tasks")).json()["count"]
    downloads_before = (await client.get("/api/downloads")).json()["count"]

    resp = await client.post("/api/agent/quick", json={
        "url": local_site.url,
        "crawl_depth": 1,
        "max_pages": 10,
        "file_types": ["jpg"],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["media_urls_found"] > 0
    assert body["pages_crawled"] >= 1
    assert all(url.endswith(".jpg") for url in body["urls"])

    # Previewing must not create a task or a download record.
    assert (await client.get("/api/agent/tasks")).json()["count"] == before
    assert (await client.get("/api/downloads")).json()["count"] == downloads_before


async def test_quick_scrape_is_available_on_every_alias(client, local_site):
    for alias in ("/api/agent", "/api/hermes", "/api/opencode", "/api/dsh",
                  "/api/codex", "/api/claude"):
        resp = await client.post(f"{alias}/quick", json={
            "url": local_site.url, "crawl_depth": 0, "max_pages": 1,
        })
        assert resp.status_code == 200, alias
        assert resp.json()["media_urls_found"] > 0, alias


async def test_fetch_downloads_one_exact_url(client, local_site, tmp_path):
    resp = await client.post("/api/agent/fetch", json={
        "url": f"{local_site.url}img/hero.jpg",
        "output_dir": str(tmp_path),
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["filename"] == "hero.jpg"
    assert body["size_bytes"] > 0
    assert (tmp_path / "hero.jpg").exists()


async def test_fetch_reports_upstream_failures(client, local_site, tmp_path):
    resp = await client.post("/api/agent/fetch", json={
        "url": f"{local_site.url}missing/gone.jpg",
        "output_dir": str(tmp_path),
    })
    assert resp.status_code == 502
    assert "404" in resp.json()["detail"]


async def test_fetch_merges_an_hls_stream(client, local_site, tmp_path):
    resp = await client.post("/api/agent/fetch", json={
        "url": f"{local_site.url}vid/stream/master.m3u8",
        "output_dir": str(tmp_path),
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["segments"] == 3
    assert body["filename"].endswith(".ts")


async def test_scrape_starts_a_task_and_reports_status(client, local_site, tmp_path):
    created = await client.post("/api/agent/scrape", json={
        "url": local_site.url,
        "name": "agent test",
        "output_dir": str(tmp_path),
        "crawl_depth": 0,
        "follow_pagination": False,
        "follow_links": False,
        "crawl_css": False,
        "crawl_iframes": False,
        "wait": True,
        "wait_timeout": 60,
    })
    assert created.status_code == 200, created.text
    body = created.json()

    assert body["status"] == "completed", body
    assert body["stats"]["completed"] > 5
    assert body["stats"]["pages_crawled"] == 1
    assert body["completed_files"]
    for entry in body["completed_files"]:
        assert entry["filename"] and entry["filepath"] and entry["size_bytes"] > 0

    # The same data is reachable through the dedicated status/results routes.
    task_id = body["task_id"]
    status = (await client.get(f"/api/agent/status/{task_id}")).json()
    assert status["status"] == "completed"
    assert status["downloads"]["completed"] == body["stats"]["completed"]
    assert status["progress"] == 100.0

    results = (await client.get(f"/api/agent/results/{task_id}")).json()
    assert len(results["completed_files"]) == body["stats"]["completed"]


async def test_status_and_results_404_for_unknown_tasks(client):
    assert (await client.get("/api/agent/status/99999")).status_code == 404
    assert (await client.get("/api/agent/results/99999")).status_code == 404
    assert (await client.post("/api/agent/cancel/99999")).status_code == 404


# ── Validation ──────────────────────────────────────────────────────────────


async def test_scrape_requires_a_url(client):
    assert (await client.post("/api/agent/scrape", json={})).status_code == 422


async def test_out_of_range_values_are_rejected(client):
    resp = await client.post("/api/agent/scrape", json={
        "url": "https://example.com", "concurrency": 999,
    })
    assert resp.status_code == 422


async def test_unknown_agent_docs_route_is_404(client):
    assert (await client.get("/api/agent/docs/unknown-tool")).status_code == 404


# ── The non-agent API still works ───────────────────────────────────────────


async def test_task_crud_and_control_routes(client):
    created = await client.post("/api/tasks", json={
        "name": "crud", "url": "example.com", "config": {"concurrency": 2},
    })
    assert created.status_code == 200
    task = created.json()["task"]
    assert task["url"] == "https://example.com", "scheme should be added"
    assert task["config_parsed"]["concurrency"] == 2
    task_id = task["id"]

    summary = await client.get(f"/api/tasks/{task_id}/summary")
    assert summary.status_code == 200
    assert "stats" in summary.json()

    stats = (await client.get("/api/tasks/stats")).json()["stats"]
    assert stats["all"] >= 1

    assert (await client.delete(f"/api/tasks/{task_id}")).status_code == 200
    assert (await client.get(f"/api/tasks/{task_id}")).status_code == 404
    assert (await client.delete(f"/api/tasks/{task_id}")).status_code == 404


async def test_download_listing_endpoints(client):
    all_downloads = await client.get("/api/downloads")
    assert all_downloads.status_code == 200
    assert "downloads" in all_downloads.json()

    per_task = await client.get("/api/tasks/1/downloads")
    assert per_task.status_code == 200
    assert "stats" in per_task.json()


async def test_settings_validation(client):
    ok = await client.put("/api/settings", json={"default_concurrency": "7"})
    assert ok.status_code == 200
    assert ok.json()["settings"]["default_concurrency"] == "7"

    bad = await client.put("/api/settings", json={"default_concurrency": "999"})
    assert bad.status_code == 400

    bad_hex = await client.put("/api/settings", json={"aes_key": "zzzz"})
    assert bad_hex.status_code == 400

    # Defaults are always present, even for keys never written.
    settings = (await client.get("/api/settings")).json()["settings"]
    assert "default_output_dir" in settings


async def test_files_listing_and_traversal_protection(client, tmp_path):
    resp = await client.get("/api/files")
    assert resp.status_code == 200
    assert "files" in resp.json()

    # Escaping the configured output directory must be refused.
    escape = await client.get("/api/files?dir=C:/Windows")
    assert escape.status_code == 403

    traversal = await client.get("/api/files/download/..%2F..%2Fetc%2Fpasswd")
    assert traversal.status_code in (403, 404)


async def test_system_endpoint_reports_the_alias_set(client):
    body = (await client.get("/api/system")).json()
    assert body["agent_count"] == len(AGENTS)
    assert body["agent_aliases"] == all_aliases()
    assert body["auth_required"] is False
