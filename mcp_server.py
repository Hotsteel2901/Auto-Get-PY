"""Auto-Get-PY as an MCP server.

Speaks the Model Context Protocol over stdio using newline-delimited JSON-RPC
2.0 — no third-party packages, so it runs anywhere the scraper runs.

Almost every modern coding agent (opencode, Claude Code, Codex, Cursor,
Windsurf, Cline, Zed, Continue, dsh, …) can attach an MCP server, which means
this one file gives all of them native tool access instead of asking the model
to remember curl incantations.

    python mcp_server.py            # stdio transport

The server proxies to the running web app (default http://127.0.0.1:8000) so
tasks started by an agent show up in the web UI and vice versa. Point it
elsewhere with ``AUTO_GET_BASE_URL``; authenticate with ``AUTO_GET_TOKEN``.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

SERVER_NAME = "auto-get-py"
SERVER_VERSION = "1.1.0"
PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2024-10-07", "2025-03-26", "2025-06-18")

BASE_URL = os.environ.get("AUTO_GET_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("AUTO_GET_TOKEN", "").strip()
API_PREFIX = os.environ.get("AUTO_GET_API_PREFIX", "/api/agent").rstrip("/")
TIMEOUT = float(os.environ.get("AUTO_GET_TIMEOUT", "600"))

JSONRPC_ERRORS = {
    "parse": -32700,
    "invalid_request": -32600,
    "method_not_found": -32601,
    "invalid_params": -32602,
    "internal": -32603,
}


# ── Tool definitions ────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "scrape",
        "description": (
            "Crawl a web page or whole site and download every media file found "
            "(images, video, audio, documents, archives). Handles pagination, "
            "sitemaps, JS-rendered pages, HLS/DASH streams, cookies and hotlink "
            "protection. Blocks until finished by default and returns the file list."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL to scrape"},
                "name": {"type": "string", "description": "Label for the task"},
                "crawl_depth": {
                    "type": "integer", "minimum": 0, "maximum": 50, "default": 0,
                    "description": "0 = start page only; N = follow links N hops"},
                "max_pages": {"type": "integer", "minimum": 1, "default": 500},
                "follow_pagination": {"type": "boolean", "default": True},
                "follow_links": {"type": "boolean", "default": False},
                "use_browser": {
                    "type": "boolean", "default": False,
                    "description": "Render with Playwright (needed for JS-heavy sites)"},
                "site_discovery": {
                    "type": "boolean", "default": False,
                    "description": "Also use sitemap.xml / robots.txt / RSS feeds"},
                "file_types": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Keep only these extensions, e.g. ['jpg','mp4']"},
                "allowed_paths": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Restrict crawling to these path prefixes"},
                "concurrency": {"type": "integer", "minimum": 1, "maximum": 50,
                                "default": 5},
                "request_delay_sec": {"type": "number", "minimum": 0, "default": 0.5},
                "max_file_size_mb": {"type": "integer", "default": 500},
                "proxy": {"type": "string"},
                "custom_headers": {"type": "object"},
                "output_dir": {"type": "string", "default": "./downloads"},
                "wait": {
                    "type": "boolean", "default": True,
                    "description": "Wait for completion. Set false for very large jobs "
                                   "and poll task_status instead."},
                "wait_timeout": {"type": "integer", "default": 600},
            },
            "required": ["url"],
        },
    },
    {
        "name": "quick_scrape",
        "description": (
            "Discover which media URLs exist on a page/site WITHOUT downloading "
            "anything. Use this first to preview, then call scrape to actually "
            "fetch the files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "crawl_depth": {"type": "integer", "minimum": 0, "maximum": 10,
                                "default": 1},
                "max_pages": {"type": "integer", "minimum": 1, "default": 50},
                "follow_pagination": {"type": "boolean", "default": True},
                "follow_links": {"type": "boolean", "default": False},
                "use_browser": {"type": "boolean", "default": False},
                "site_discovery": {"type": "boolean", "default": False},
                "file_types": {"type": "array", "items": {"type": "string"}},
                "proxy": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "fetch_file",
        "description": (
            "Download exactly one URL to disk. No crawling. Handles HLS (.m3u8) "
            "and DASH (.mpd) playlists by fetching and merging their segments."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "output_dir": {"type": "string", "default": "./downloads"},
                "filename": {"type": "string"},
                "referer": {"type": "string"},
                "headers": {"type": "object"},
                "proxy": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "task_status",
        "description": "Progress of a running or finished scrape task.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "task_results",
        "description": "Final file list for a task: paths, sizes and failures.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "cancel_task",
        "description": "Stop a running scrape task and free its workers.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "list_files",
        "description": "List files already downloaded to disk, newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 100}},
        },
    },
    {
        "name": "list_agents",
        "description": (
            "List the coding agents this scraper integrates with and the URL alias "
            "each one uses, plus the service manifest."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ── HTTP plumbing ───────────────────────────────────────────────────────────


class ServiceError(RuntimeError):
    """Raised when the scraper service cannot be reached or returns an error."""


def api_request(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{BASE_URL}{API_PREFIX}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    if TOKEN:
        request.add_header("Authorization", f"Bearer {TOKEN}")

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except json.JSONDecodeError:
            pass
        raise ServiceError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ServiceError(
            f"Cannot reach the scraper at {BASE_URL} ({exc.reason}). "
            f"Start it with `python app.py` in the Auto-Get-PY checkout."
        ) from exc
    except TimeoutError as exc:
        raise ServiceError(
            f"Request to {url} timed out after {TIMEOUT:.0f}s.") from exc

    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ServiceError(f"Service returned non-JSON: {body[:200]}") from exc


def _drop_none(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if v is not None}


# ── Tool implementations ────────────────────────────────────────────────────


def tool_scrape(args: dict) -> dict:
    payload = _drop_none(dict(args))
    payload.setdefault("wait", True)
    payload.setdefault("wait_timeout", 600)
    result = api_request("POST", "/scrape", payload)

    # A timeout is not a failure: hand back the task id so the agent can poll.
    if result.get("status") == "timeout":
        return {
            "status": "running",
            "task_id": result.get("task_id"),
            "message": result.get("message"),
            "hint": "Call task_status with this task_id until it finishes.",
        }
    return _summarise(result)


def tool_quick_scrape(args: dict) -> dict:
    result = api_request("POST", "/quick", _drop_none(dict(args)))
    urls = result.get("urls") or []
    return {
        "url": result.get("url"),
        "media_urls_found": result.get("media_urls_found", len(urls)),
        "pages_crawled": result.get("pages_crawled", 0),
        "urls": urls,
    }


def tool_fetch_file(args: dict) -> dict:
    payload = _drop_none(dict(args))
    payload["max_file_size_mb"] = 0
    result = api_request("POST", "/fetch", payload)
    return {
        "status": result.get("status"),
        "filename": result.get("filename"),
        "filepath": result.get("filepath"),
        "size_bytes": result.get("size_bytes"),
        "mime_type": result.get("mime_type"),
        "segments": result.get("segments"),
    }


def tool_task_status(args: dict) -> dict:
    result = api_request("GET", f"/status/{int(args['task_id'])}")
    return {
        "task_id": result.get("task_id"),
        "status": result.get("status"),
        "progress": result.get("progress"),
        "done_files": result.get("done_files"),
        "total_files": result.get("total_files"),
        "downloads": result.get("downloads"),
        "pages_crawled": result.get("pages_crawled"),
        "total_media_found": result.get("total_media_found"),
        "error_msg": result.get("error_msg"),
    }


def tool_task_results(args: dict) -> dict:
    return _summarise(api_request("GET", f"/results/{int(args['task_id'])}"))


def tool_cancel_task(args: dict) -> dict:
    return api_request("POST", f"/cancel/{int(args['task_id'])}")


def tool_list_files(args: dict) -> dict:
    limit = int(args.get("limit") or 100)
    result = api_request("GET", f"/files?{urllib.parse.urlencode({'limit': limit})}")
    files = result.get("files") or []
    return {
        "directory": result.get("directory"),
        "total": result.get("total", len(files)),
        "files": [
            {"name": f.get("name"), "path": f.get("path"), "size": f.get("size")}
            for f in files
        ],
    }


def tool_list_agents(_args: dict) -> dict:
    manifest = api_request("GET", "/manifest")
    return {
        "service": manifest.get("service"),
        "canonical_prefix": manifest.get("canonical_prefix"),
        "aliases": manifest.get("aliases"),
        "capabilities": manifest.get("capabilities"),
        "agents": manifest.get("agents"),
    }


HANDLERS = {
    "scrape": tool_scrape,
    "quick_scrape": tool_quick_scrape,
    "fetch_file": tool_fetch_file,
    "task_status": tool_task_status,
    "task_results": tool_task_results,
    "cancel_task": tool_cancel_task,
    "list_files": tool_list_files,
    "list_agents": tool_list_agents,
}


def _summarise(result: dict) -> dict:
    """Trim a results payload to what a model actually needs to see."""
    if "completed_files" not in result:
        return result
    stats = result.get("stats") or {}
    files = result.get("completed_files") or []
    return {
        "task_id": result.get("task_id"),
        "status": result.get("status"),
        "output_dir": result.get("output_dir"),
        "stats": stats,
        "downloaded": [
            {"filename": f.get("filename"), "size_bytes": f.get("size_bytes"),
             "filepath": f.get("filepath")}
            for f in files[:500]
        ],
        "truncated": len(files) > 500,
        "failed": result.get("failed_files") or [],
        "error_msg": result.get("error_msg"),
    }


# ── JSON-RPC layer ──────────────────────────────────────────────────────────


def _result(request_id, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _text(content: str) -> dict:
    return {"content": [{"type": "text", "text": content}]}


def handle(message: dict) -> dict | None:
    """Handle one JSON-RPC message. Returns None for notifications."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if request_id is None and method and method.startswith("notifications/"):
        return None

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return _result(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Media scraper. Use quick_scrape to preview what a page contains, "
                "then scrape to download. Use fetch_file for a single known URL, "
                "including HLS/DASH streams."
            ),
        })

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            return _error(request_id, JSONRPC_ERRORS["method_not_found"],
                          f"Unknown tool '{name}'")
        if not isinstance(arguments, dict):
            return _error(request_id, JSONRPC_ERRORS["invalid_params"],
                          "arguments must be an object")
        try:
            payload = handler(arguments)
        except ServiceError as exc:
            return _result(request_id, {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            })
        except (KeyError, TypeError, ValueError) as exc:
            return _result(request_id, {
                "content": [{"type": "text",
                             "text": f"Invalid arguments for '{name}': {exc}"}],
                "isError": True,
            })
        except Exception as exc:  # noqa: BLE001 - report, never crash the server
            return _result(request_id, {
                "content": [{"type": "text",
                             "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            })
        return _result(request_id, _text(json.dumps(payload, ensure_ascii=False,
                                                    indent=2)))

    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        return _result(request_id, {key: []})

    if request_id is None:
        return None
    return _error(request_id, JSONRPC_ERRORS["method_not_found"],
                  f"Method '{method}' is not supported")


def main() -> int:
    """Read newline-delimited JSON-RPC from stdin, write replies to stdout."""
    stdin = sys.stdin
    stdout = sys.stdout

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps(_error(None, JSONRPC_ERRORS["parse"],
                                           "Invalid JSON")) + "\n")
            stdout.flush()
            continue

        if isinstance(message, list):
            replies = [r for r in (handle(m) for m in message) if r is not None]
            if replies:
                stdout.write(json.dumps(replies) + "\n")
                stdout.flush()
            continue

        try:
            reply = handle(message)
        except Exception as exc:  # noqa: BLE001 - a bad request must not kill us
            reply = _error(message.get("id"), JSONRPC_ERRORS["internal"], str(exc))

        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
