"""Renders the agent-facing documentation.

One canonical body of text describes the HTTP API.  :func:`render_skill` and
:func:`render_agent_doc` wrap it with the front-matter, install steps and
tool-specific notes that each agent expects, so the served skill and the files
committed to the repository can never drift apart.
"""

from __future__ import annotations

import json
from datetime import date

from api.agent_registry import AGENTS, AgentDescriptor

PROJECT_NAME = "Auto-Get-PY"
DEFAULT_BASE_URL = "http://localhost:8000"

# ── Capability list shared by every generated document ──────────────────────

CAPABILITIES = """\
- Static HTML, JSON-LD, `srcset`, lazy `data-*`, CSS `url()`, `<noscript>`,
  `<template>`, inline `<script>` strings, Open Graph and Twitter cards
- Pagination (`rel=next`, Chinese 下一页/下一頁, class-based, `?page=N` chains)
- Recursive link crawling bounded by depth, page count and allowed path prefixes
- sitemap.xml, robots.txt, RSS/Atom feeds (site discovery)
- Stylesheet and iframe traversal
- Playwright rendering for JavaScript-heavy sites, with network capture
- Cookie and `Referer` propagation — required by hotlink-protected CDNs
- HLS (`.m3u8`) and DASH (`.mpd`) merging, including AES-128 encrypted segments
- Resume of interrupted downloads, retries with exponential backoff, 429 handling
- Pluggable decryptors: base64, hex, AES-CBC/ECB/GCM, XOR, ROT47, URL-sign strip,
  custom Python expression
"""

# ── Canonical endpoint table ────────────────────────────────────────────────

ENDPOINTS = [
    ("POST", "/scrape", "Crawl a page/site and download everything found. "
                        "Returns a `task_id`, or the final result when `wait=true`."),
    ("POST", "/quick", "Discover media URLs only — nothing is written to disk. "
                       "Use this to preview before downloading."),
    ("POST", "/direct", "Playwright render + immediate download, synchronous. "
                        "Best for single JS-heavy pages."),
    ("POST", "/fetch", "Download one exact URL. No crawling."),
    ("GET", "/status/{task_id}", "Progress, per-status download counts, error."),
    ("GET", "/results/{task_id}", "Final file list with paths and sizes."),
    ("POST", "/cancel/{task_id}", "Stop a running task and free its workers."),
    ("GET", "/tasks", "Recent tasks."),
    ("GET", "/files", "Files on disk, newest first."),
    ("GET", "/manifest", "Machine-readable capability + endpoint manifest."),
    ("GET", "/agents", "Every supported agent and its URL alias."),
    ("GET", "/skill", "This document, served as markdown (`?agent=<id>`)."),
]

SCENARIOS = [
    ("Image gallery",
     {"url": "https://example.com/gallery/", "crawl_depth": 2,
      "follow_pagination": True, "file_types": ["jpg", "png", "webp"]}),
    ("Video page",
     {"url": "https://example.com/watch/123", "use_browser": True,
      "file_types": ["mp4", "m3u8", "webm"]}),
    ("Full site mirror",
     {"url": "https://example.com/", "site_discovery": True, "crawl_depth": 5,
      "max_pages": 10000, "follow_links": True, "follow_pagination": True}),
    ("JavaScript SPA",
     {"url": "https://example.com/", "use_browser": True, "crawl_depth": 3,
      "max_scrolls": 50}),
    ("Behind a proxy",
     {"url": "https://example.com/", "proxy": "http://127.0.0.1:7890",
      "crawl_depth": 2}),
    ("Login-gated / hotlink-protected",
     {"url": "https://example.com/", "crawl_css": True, "crawl_iframes": True,
      "custom_headers": {"Cookie": "session=...", "Referer": "https://example.com/"}}),
]


def _endpoint_table(prefix: str) -> str:
    lines = ["| Method | Path | Purpose |", "|---|---|---|"]
    for method, path, purpose in ENDPOINTS:
        lines.append(f"| `{method}` | `{prefix}{path}` | {purpose} |")
    return "\n".join(lines)


def _scenario_block(prefix: str) -> str:
    blocks = []
    for title, body in SCENARIOS:
        payload = json.dumps(body, indent=2, ensure_ascii=False)
        endpoint = "/quick" if title == "Image gallery" else "/scrape"
        blocks.append(
            f"### {title}\n\n```bash\ncurl -s {_curl_base(prefix)}{endpoint} \\\n"
            f"  -H 'Content-Type: application/json' \\\n"
            f"  -d '{json.dumps(body, ensure_ascii=False)}'\n```\n\n"
            f"```json\n{payload}\n```"
        )
    return "\n\n".join(blocks)


def _curl_base(prefix: str) -> str:
    return f"{DEFAULT_BASE_URL}{prefix}"


def canonical_body(prefix: str, base_url: str = DEFAULT_BASE_URL) -> str:
    """The tool-independent body of the documentation."""
    curl = f"{base_url.rstrip('/')}{prefix}"
    return f"""\
## What this service does

`{PROJECT_NAME}` is a local, self-hosted media scraper. It takes a URL, finds
every downloadable asset reachable from it, and writes them to disk.

{_paragraphise(CAPABILITIES)}

## Base URL

```
{base_url.rstrip('/')}
```

All endpoints below are relative to `{prefix}`. The service must be running:
start it with `python app.py` inside the `{PROJECT_NAME}` checkout. Check
`GET {curl}/health` first — it returns `{{"status": "ok"}}`.

## Endpoints

{_endpoint_table(prefix)}

## Response shapes

`POST /scrape` with `wait: false`:

```json
{{
  "task_id": 7,
  "status": "running",
  "status_url": "{prefix}/status/7",
  "results_url": "{prefix}/results/7"
}}
```

`GET /status/{{id}}`:

```json
{{
  "task_id": 7,
  "status": "running",
  "progress": 42.5,
  "total_files": 120,
  "done_files": 51,
  "downloads": {{"pending": 60, "downloading": 5, "completed": 51,
                "failed": 4, "total": 120, "bytes": 81234567}},
  "pages_crawled": 18,
  "total_media_found": 120,
  "error_msg": null
}}
```

`GET /results/{{id}}`:

```json
{{
  "task_id": 7,
  "status": "completed",
  "output_dir": "./downloads",
  "stats": {{"total_files": 120, "completed": 116, "failed": 4,
            "total_size_bytes": 81234567, "pages_crawled": 18}},
  "completed_files": [
    {{"filename": "photo-01.jpg", "url": "https://…", "size_bytes": 204800,
      "filepath": "./downloads/photo-01.jpg", "mime_type": "image/jpeg"}}
  ],
  "failed_files": [{{"filename": "x.mp4", "url": "https://…", "error": "HTTP 403"}}]
}}
```

`status` is one of `running`, `paused`, `completed`, `failed`, `cancelled`.

## Recommended workflow

When a user asks to "scrape", "crawl", "download the images/videos from", or
uses 爬取 / 抓取 / 爬图 / 批量下载:

1. **Health check** — `GET /health`. If it fails, the service is not running;
   tell the user to start it instead of guessing.
2. **Preview** — `POST /quick` with `crawl_depth: 2`. Report how many assets
   were found and a few example URLs.
3. **Confirm** — only download after the user agrees, unless they already said
   "just download it".
4. **Download** — `POST /scrape`. Use `wait: true` for small jobs and polling
   for large ones.
5. **Track** — poll `GET /status/{{id}}` every few seconds and report progress.
6. **Report** — `GET /results/{{id}}`, then summarise: how many files, where
   they are, what failed and why.

## Scenario templates

{_scenario_block(prefix)}

## Parameter reference

| Field | Type | Default | Meaning |
|---|---|---|---|
| `url` | string | required | Target page |
| `name` | string | `"Agent task"` | Label shown in the web UI |
| `crawl_depth` | int | `0` | `0` = start page only; `N` = follow links `N` hops |
| `max_pages` | int | `500` | Hard cap on pages fetched |
| `max_media` | int | `20000` | Hard cap on discovered assets |
| `max_links_per_page` | int | `20` | Links followed per page |
| `follow_pagination` | bool | `true` | Follow the next-page chain |
| `follow_links` | bool | `false` | Follow `<a href>` links |
| `allowed_paths` | string[] | `null` | Restrict crawling to these path prefixes |
| `use_browser` | bool | `false` | Render with Playwright (needs `playwright install chromium`) |
| `crawl_css` | bool | `true` | Harvest assets referenced by stylesheets |
| `crawl_iframes` | bool | `true` | Enter iframes |
| `site_discovery` | bool | `false` | Use sitemap.xml / robots.txt / feeds |
| `extract_base64` | bool | `false` | Save inline `data:` images |
| `probe_links` | bool | `false` | HEAD-probe extension-less download links |
| `file_types` | string[] | `null` | Keep only these extensions, e.g. `["jpg","mp4"]` |
| `concurrency` | int | `5` | Parallel downloads (1–50) |
| `request_delay_sec` | float | `0.5` | Delay between requests; raise it for fragile sites |
| `request_timeout_sec` | int | `30` | Per-request timeout |
| `max_retries` | int | `3` | Retries per file, exponential backoff |
| `max_file_size_mb` | int | `500` | Skip anything larger; `0` disables the limit |
| `proxy` | string | `null` | `http://`, `https://` or `socks5://` |
| `custom_headers` | object | `null` | e.g. `Cookie`, `Referer`, `Authorization` |
| `decryptors` | string[] | `null` | `base64`, `hex`, `aes`, `xor`, `url_sign`, `rot47`, `custom` |
| `decryptor_opts` | object | `null` | e.g. `{{"aes": {{"key": "…hex…", "iv": "…hex…"}}}}` |
| `output_dir` | string | `"./downloads"` | Where files land |
| `wait` | bool | `false` | Block until the task finishes |
| `wait_timeout` | int | `300` | Max seconds to block |

## Behaviour worth knowing

- **Cookies are carried across the whole task.** A page that sets a session
  cookie before serving media will work, because the same HTTP session is
  reused for the downloads.
- **`Referer` is set per asset**, pointing at the page that referenced it. This
  defeats most hotlink protection.
- **HLS/DASH are merged.** A `.m3u8` becomes a single playable `.ts` (or `.mp4`
  for fragmented streams) rather than a pile of segments.
- **Interrupted downloads resume** from the bytes already on disk; retries do
  not create `(1)`/`(2)` copies.
- **Files are never overwritten by a different asset** — names are made unique
  per task.
- **Failed files still appear in `/results`** with the reason, so you can report
  honestly instead of claiming success.
- `output_dir` is resolved relative to the server process, not the caller.
- This is a local single-user tool. Do not expose it to the internet.
"""


def _paragraphise(block: str) -> str:
    return "\n".join(block.strip().splitlines())


def render_skill(agent: AgentDescriptor, base_url: str = DEFAULT_BASE_URL) -> str:
    """A `SKILL.md`-style document with YAML front matter."""
    prefix = agent.primary_prefix
    triggers = "\n".join(f"  - {trigger}" for trigger in agent.triggers)
    front_matter = f"""\
---
name: auto-get-py
description: >-
  Scrape any web page or site for media files (images, video, audio, documents,
  archives) and download them. Handles pagination, sitemaps, JS-rendered pages,
  HLS/DASH streams, hotlink protection and cookies.
version: 1.1.0
tags: [scraper, media, download, crawler, hls, playwright]
allowed-tools: Bash, Read, Glob
triggers:
{triggers}
---
"""
    return f"""{front_matter}
# Auto-Get-PY — media scraper for {agent.name}

{canonical_body(prefix, base_url)}

## {agent.name} specifics

{_agent_specifics(agent)}
"""


def render_agent_doc(agent: AgentDescriptor, base_url: str = DEFAULT_BASE_URL) -> str:
    """The plain-markdown document written into the repository."""
    return f"""\
# {PROJECT_NAME} integration — {agent.name}

> Generated from `api/agent_registry.py` on {date.today().isoformat()}.
> Do not edit by hand; run `python scripts/generate_agent_docs.py`.

**Vendor:** {agent.vendor}
**URL alias:** `{agent.primary_prefix}` (canonical: `{agent.api_prefix}`)
**Config files written:** {", ".join(f"`{path}`" for path in agent.config_files) or "—"}

## Setup

{agent.install or "Start the service with `python app.py`, then call the API."}

## How to install it

{_install_steps(agent)}

{canonical_body(agent.primary_prefix, base_url)}

## {agent.name} specifics

{_agent_specifics(agent)}
"""


def _agent_specifics(agent: AgentDescriptor) -> str:
    aliases = ", ".join(f"`{alias}`" for alias in agent.aliases)
    lines = [
        f"- This tool can reach the API at {aliases} — identical responses to "
        f"`{agent.api_prefix}`.",
        f"- Canonical prefix: `{agent.api_prefix}`.",
    ]
    if agent.config_files:
        lines.append("- Files provided for this tool: "
                     + ", ".join(f"`{path}`" for path in agent.config_files) + ".")
    if agent.notes:
        lines.append(f"- {agent.notes}")
    if agent.docs_url:
        lines.append(f"- {agent.name} documentation: {agent.docs_url}")
    return "\n".join(lines)


def _install_steps(agent: AgentDescriptor) -> str:
    steps = [
        "1. Clone this repository and install the dependencies:",
        "",
        "   ```bash",
        "   pip install -r requirements.txt",
        "   python app.py",
        "   ```",
        "",
        f"2. Confirm the service is up: `curl {DEFAULT_BASE_URL}/api/health`",
        "",
        "3. Make the agent aware of the API — either:",
        "",
    ]
    if agent.config_files:
        for path in agent.config_files:
            steps.append(f"   - commit/keep `{path}` (already generated in this repo), or")
    steps.append(f"   - paste the contents of the skill document at "
                 f"`{DEFAULT_BASE_URL}{agent.api_prefix}/skill?agent={agent.id}`")
    steps.append("")
    steps.append(f"4. Optional: for JS-heavy targets run "
                 f"`playwright install chromium`.")
    return "\n".join(steps)


# ── Manifest ────────────────────────────────────────────────────────────────


def build_manifest(base_url: str = DEFAULT_BASE_URL) -> dict:
    """A machine-readable description an agent can self-configure from."""
    return {
        "service": PROJECT_NAME,
        "version": "1.1.0",
        "description": "Local media scraper: crawl a site, download every asset.",
        "base_url": base_url.rstrip("/"),
        "canonical_prefix": "/api/agent",
        "aliases": sorted({alias for agent in AGENTS for alias in agent.aliases}),
        "auth": {"type": "none", "note": "Local single-user service."},
        "endpoints": [
            {"method": method, "path": path, "purpose": purpose}
            for method, path, purpose in ENDPOINTS
        ],
        "capabilities": [
            "html-extraction", "json-ld", "srcset", "lazy-load", "css-urls",
            "noscript-template", "pagination", "recursive-crawl", "sitemap",
            "robots", "rss-atom", "iframe", "playwright-render", "network-capture",
            "cookies", "referer", "hls-merge", "hls-aes128", "dash-merge",
            "resume", "retry-backoff", "rate-limit-handling", "decryptors",
        ],
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
                "alias": agent.primary_prefix,
                "skill_url": f"/api/agent/skill?agent={agent.id}",
            }
            for agent in AGENTS
        ],
        "openapi_url": "/openapi.json",
        "docs_url": "/docs",
    }
