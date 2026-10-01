"""MCP server tests.

The server speaks newline-delimited JSON-RPC 2.0 over stdio. Most tests drive
it in-process; one spawns the real process to prove the stdio framing works.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import mcp_server

ROOT = Path(__file__).resolve().parent.parent


def call(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return mcp_server.handle(message)


# ── Protocol ────────────────────────────────────────────────────────────────


def test_initialize_negotiates_a_known_protocol_version():
    reply = call("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    })
    result = reply["result"]
    assert reply["jsonrpc"] == "2.0"
    assert reply["id"] == 1
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "auto-get-py"
    assert "tools" in result["capabilities"]


def test_initialize_falls_back_for_an_unknown_protocol_version():
    reply = call("initialize", {"protocolVersion": "1999-01-01"})
    assert reply["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSION


def test_notifications_produce_no_reply():
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping_is_answered():
    assert call("ping")["result"] == {}


def test_unknown_method_is_method_not_found():
    reply = call("does/not/exist")
    assert reply["error"]["code"] == -32601


def test_tools_list_shape():
    tools = call("tools/list")["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {"scrape", "quick_scrape", "fetch_file", "task_status",
            "task_results", "cancel_task", "list_files", "list_agents"} == names
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert "properties" in tool["inputSchema"]


def test_every_tool_schema_defaults_are_valid_json_types():
    for tool in call("tools/list")["result"]["tools"]:
        for prop, spec in tool["inputSchema"]["properties"].items():
            assert "type" in spec or "anyOf" in spec, f"{tool['name']}.{prop} has no type"
            json.dumps(spec)  # must be serialisable


# ── Error handling ──────────────────────────────────────────────────────────


def test_unknown_tool_is_reported():
    reply = call("tools/call", {"name": "nope", "arguments": {}})
    assert reply["error"]["code"] == -32601


def test_missing_arguments_surface_as_a_tool_error_not_a_crash(monkeypatch):
    """A required field is enforced by the schema, but a handler KeyError must
    still come back as an isError result rather than killing the server."""
    reply = call("tools/call", {"name": "task_status", "arguments": {}})
    assert reply["result"]["isError"] is True
    assert "task_status" in reply["result"]["content"][0]["text"]


def test_unreachable_service_produces_a_helpful_message(monkeypatch):
    def explode(*_args, **_kwargs):
        raise mcp_server.ServiceError(
            "Cannot reach the scraper at http://127.0.0.1:8000. "
            "Start it with `python app.py`.")

    monkeypatch.setattr(mcp_server, "api_request", explode)
    reply = call("tools/call", {"name": "list_files", "arguments": {}})
    assert reply["result"]["isError"] is True
    text = reply["result"]["content"][0]["text"]
    assert "python app.py" in text


def test_arguments_must_be_an_object():
    reply = call("tools/call", {"name": "scrape", "arguments": "nope"})
    assert reply["error"]["code"] == -32602


def test_results_are_summarised_for_the_model(monkeypatch):
    payload = {
        "task_id": 3, "status": "completed", "output_dir": "./downloads",
        "stats": {"completed": 2},
        "completed_files": [
            {"filename": f"f{i}.jpg", "url": "u", "size_bytes": i, "filepath": "p"}
            for i in range(600)
        ],
        "failed_files": [{"filename": "x", "url": "u", "error": "HTTP 403"}],
    }
    monkeypatch.setattr(mcp_server, "api_request", lambda *a, **k: payload)
    reply = call("tools/call", {"name": "task_results", "arguments": {"task_id": 3}})
    body = json.loads(reply["result"]["content"][0]["text"])
    assert len(body["downloaded"]) == 500
    assert body["truncated"] is True
    assert body["failed"][0]["error"] == "HTTP 403"


def test_scrape_forwards_to_the_wait_endpoint(monkeypatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured["method"], captured["path"], captured["payload"] = method, path, payload
        return {"task_id": 9, "status": "completed", "stats": {},
                "completed_files": [], "failed_files": []}

    monkeypatch.setattr(mcp_server, "api_request", fake_request)
    reply = call("tools/call", {"name": "scrape",
                                "arguments": {"url": "https://example.com"}})
    assert captured["method"] == "POST"
    assert captured["path"] == "/scrape"
    assert captured["payload"]["wait"] is True
    assert captured["payload"]["url"] == "https://example.com"
    # `isError` is optional in MCP and defaults to false, so a success result
    # legitimately omits it.
    assert reply["result"].get("isError", False) is False
    assert reply["result"]["content"][0]["type"] == "text"


def test_scrape_timeout_is_not_treated_as_failure(monkeypatch):
    monkeypatch.setattr(mcp_server, "api_request", lambda *a, **k: {
        "task_id": 12, "status": "timeout", "message": "still running"})
    reply = call("tools/call", {"name": "scrape",
                                "arguments": {"url": "https://example.com"}})
    body = json.loads(reply["result"]["content"][0]["text"])
    assert body["status"] == "running"
    assert body["task_id"] == 12
    assert "task_status" in body["hint"]


def test_fetch_file_disables_the_size_cap(monkeypatch):
    captured = {}
    monkeypatch.setattr(mcp_server, "api_request",
                        lambda m, p, payload=None: captured.update(payload) or {
                            "status": "completed", "filename": "a.jpg"})
    call("tools/call", {"name": "fetch_file",
                        "arguments": {"url": "https://e.com/a.jpg"}})
    assert captured["max_file_size_mb"] == 0


# ── Real stdio process ──────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform.startswith("win") and not sys.executable,
                    reason="needs a usable python")
def test_stdio_transport_end_to_end():
    """Spawn the server and speak to it over real pipes."""
    messages = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        "",
    ])

    completed = subprocess.run(
        [sys.executable, "mcp_server.py"],
        input=messages, capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 2, completed.stdout

    init = json.loads(lines[0])
    assert init["id"] == 1
    assert init["result"]["serverInfo"]["name"] == "auto-get-py"

    tools = json.loads(lines[1])
    assert tools["id"] == 2
    assert len(tools["result"]["tools"]) == 8


def test_invalid_json_gets_a_parse_error(monkeypatch):
    """The main loop must answer a malformed line instead of dying."""
    completed = subprocess.run(
        [sys.executable, "mcp_server.py"],
        input="{not json}\n", capture_output=True, text=True, timeout=60,
        cwd=str(ROOT), encoding="utf-8",
    )
    assert completed.returncode == 0
    reply = json.loads(completed.stdout.strip().splitlines()[0])
    assert reply["error"]["code"] == -32700
