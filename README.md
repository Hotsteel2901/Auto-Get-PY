# Auto-Get-PY

> A universal media scraper. Point it at a page or a whole site; it finds every
> image, video, audio file, document and archive and downloads them.

**AI-generated project** — this codebase was produced by Claude Code
(Anthropic) through iterative design, implementation and review cycles. A human
supplied the requirements and direction; the AI wrote the code, tests, docs and
commits.

---

## What it actually does

| Capability | Detail |
|---|---|
| **Deep extraction** | `src`, `href`, `srcset`, lazy `data-*`, CSS `url()`, `<noscript>`, `<template>`, JSON-LD, Open Graph, Twitter cards, inline `<script>` strings, `data:` images |
| **Crawling** | `rel=next` and 下一页 pagination, recursive link following, stylesheet traversal (including nested `@import`), iframes, `<meta refresh>` redirects |
| **Site discovery** | `sitemap.xml` (including sitemap indexes), `robots.txt`, RSS and Atom feeds |
| **JavaScript sites** | Playwright rendering with auto-scroll and network capture; browser cookies are merged into the download session |
| **Protected media** | Cookies are carried across the whole task and each asset is requested with the `Referer` of the page that referenced it |
| **Streams** | HLS (`.m3u8`) and DASH (`.mpd`) are resolved and merged into a single playable file, including AES-128 encrypted HLS segments |
| **Transfer** | Concurrent downloads, resume from partial files, retries with exponential backoff, `Retry-After` handling, per-file size limits |
| **Decryptors** | base64, hex, AES-CBC/ECB/GCM, XOR, ROT47, URL-signature stripping, custom Python expression |
| **Web UI** | Dark SPA with live WebSocket progress, task control, file browser, and a page documenting every agent integration |
| **Agent API** | One REST API mounted under 17 tool-specific aliases, plus a dependency-free MCP server |

---

## Quick start

```bash
git clone https://github.com/Hotsteel2901/Auto-Get-PY.git
cd Auto-Get-PY
pip install -r requirements.txt

python app.py                       # http://127.0.0.1:8000
python app.py --port 9090 --reload  # custom port / dev mode
```

Open **http://127.0.0.1:8000** for the web UI.

Optional, only for JavaScript-heavy sites:

```bash
pip install playwright && playwright install chromium
```

### Security note

The server binds to `127.0.0.1` by default. If you expose it (`--host 0.0.0.0`),
set a token first:

```bash
AUTO_GET_TOKEN=my-secret python app.py --host 0.0.0.0
```

Every `/api/**` request then needs `Authorization: Bearer my-secret`,
`X-API-Token: my-secret`, or `?token=my-secret`. Without a token the server
warns on startup rather than refusing to run.

---

## Use it from an agent

The scraper is designed to be driven by coding agents. Every tool gets the same
API under the path it already expects:

| Tool | Alias | Tool | Alias |
|---|---|---|---|
| Any HTTP agent | `/api/agent` | Cursor | `/api/cursor` |
| Hermes Agent | `/api/hermes` | GitHub Copilot | `/api/copilot` |
| opencode | `/api/opencode` | Cline / Roo / Windsurf | `/api/cline`, `/api/roo`, `/api/windsurf` |
| DeepSeek Harness (dsh) | `/api/dsh` | Continue / Aider / Zed | `/api/continue`, `/api/aider`, `/api/zed` |
| OpenAI Codex CLI | `/api/codex` | Amp / Jules | `/api/amp`, `/api/jules` |
| Claude Code | `/api/claude` | Gemini CLI | `/api/gemini` |

The repository ships the config file each tool reads — `AGENTS.md`,
`CLAUDE.md`, `GEMINI.md`, `opencode.json`, `.cursor/rules/`, `.codex/`,
`.dsh/skills/`, `.clinerules/`, and so on. All of them are generated from one
registry:

```bash
python scripts/generate_agent_docs.py          # regenerate
python scripts/generate_agent_docs.py --check  # fail if stale (used in CI)
```

### MCP

Most of these tools speak the Model Context Protocol, so `mcp_server.py`
exposes the scraper as eight native tools over stdio — no HTTP plumbing needed:

```json
{
  "mcpServers": {
    "auto-get-py": {
      "command": "python",
      "args": ["mcp_server.py"],
      "env": { "AUTO_GET_BASE_URL": "http://localhost:8000" }
    }
  }
}
```

Tools: `scrape`, `quick_scrape`, `fetch_file`, `task_status`, `task_results`,
`cancel_task`, `list_files`, `list_agents`. The server has no dependencies
beyond the standard library.

### REST, three commands

```bash
# 1. Is it running?
curl -s http://localhost:8000/api/health

# 2. What is on the page? (no downloads)
curl -s http://localhost:8000/api/agent/quick \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/gallery/", "crawl_depth": 2}'

# 3. Fetch everything
curl -s http://localhost:8000/api/agent/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/gallery/", "wait": true, "crawl_depth": 2}'
```

An agent can also read `GET /api/agent/manifest` and configure itself, and
`GET /api/agent/skill?agent=codex` returns a ready-to-paste skill document.

---

## API reference

### Agent endpoints (all aliases)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/scrape` | Crawl and download. Returns a task handle, or the result with `wait: true` |
| `POST` | `/quick` | Discover media URLs only — nothing is written to disk |
| `POST` | `/direct` | Playwright render + immediate download, synchronous |
| `POST` | `/fetch` | Download exactly one URL (handles HLS/DASH) |
| `GET` | `/status/{id}` | Progress, per-status counts, error |
| `GET` | `/results/{id}` | Final file list with paths and sizes |
| `POST` | `/cancel/{id}` | Stop a task and free its workers |
| `GET` | `/tasks`, `/files` | Recent tasks, files on disk |
| `GET` | `/manifest`, `/agents`, `/skill` | Self-configuration documents |

### Management endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/tasks` | Task list (`status`, `offset`, `limit`) |
| `POST` | `/api/tasks` | Create a task |
| `GET` | `/api/tasks/{id}/summary` | Task plus download statistics |
| `PUT`/`DELETE` | `/api/tasks/{id}` | Update / delete |
| `POST` | `/api/tasks/{id}/{start,pause,resume,cancel,retry}` | Lifecycle control |
| `GET` | `/api/tasks/stats` | Status counts for the dashboard |
| `GET` | `/api/downloads` | Every download across every task |
| `GET` | `/api/tasks/{id}/downloads` | Downloads for one task |
| `GET`/`PUT` | `/api/settings` | Global defaults (validated) |
| `GET` | `/api/files` | Browse the output directory |
| `GET` | `/api/files/download/{path}` | Download a file (`?inline=true` to preview) |
| `DELETE` | `/api/files/{path}` | Delete a file |
| `WS` | `/ws/progress` | `progress`, `file_progress`, `task_status` events |
| `GET` | `/docs`, `/openapi.json` | Interactive API documentation |

---

## Web UI

A light-first single-page app — white cards on a soft neutral canvas, one blue
accent, soft shadows instead of hard borders. Every page is driven by one live
WebSocket channel.

- **Dashboard** — status tiles, live per-task progress, inline pause/resume/stop/retry
- **New task** — target, recipe presets, file-type chips, discovery toggles, decryptors, network options, headers, and a live URL preview
- **Downloads** — every record with live byte counts, filters, search and CSV export
- **Files** — what is on disk, with preview, download and delete
- **Agents** — the integration surface: aliases, config files and setup snippets for every supported tool
- **Settings** — task defaults, AES keys, API token and runtime facts

### Language

The interface ships in **Chinese and English** and switches instantly, with no
reload and no page losing its state. The choice is remembered per browser.

- Click the `中` / `EN` button at the bottom of the sidebar.
- Or link straight to a language: `http://localhost:8000/?lang=en` (also
  `?lang=zh`).

The default is Chinese; add `?lang=en` if you prefer English.

### Theme

Light by default, with a dark theme one click away (the sun/moon button next to
the language switch). The choice persists and is applied before first paint, so
there is no flash of the wrong theme.

### Keyboard

`/` focuses the current page's search box · `g d` `g n` `g l` `g f` `g a` `g s`
navigate · `Esc` closes dialogs.

---

## Task configuration

```json
{
  "concurrency": 5,
  "output_dir": "./downloads",

  "crawl_depth": 2,
  "max_pages": 500,
  "max_media": 20000,
  "follow_pagination": true,
  "follow_links": false,
  "allowed_paths": ["/gallery/"],

  "crawl_css": true,
  "crawl_iframes": true,
  "site_discovery": false,
  "use_browser": false,
  "scroll_page": true,
  "max_scrolls": 30,
  "extract_base64": false,
  "probe_links": false,

  "url_filters": { "include": ["*.jpg", "*.mp4"], "exclude": ["*.gif"] },
  "custom_headers": { "Referer": "https://example.com", "Cookie": "session=..." },
  "proxy": "http://127.0.0.1:7890",

  "request_delay_sec": 0.5,
  "request_timeout_sec": 30,
  "max_retries": 3,
  "max_file_size_mb": 500,

  "decryptors": ["base64", "aes"],
  "decryptor_opts": { "aes": { "key": "…hex…", "iv": "…hex…", "mode": "cbc" } }
}
```

### Recipes

| Goal | Configuration |
|---|---|
| Single page | `crawl_depth: 0, follow_pagination: false` |
| Gallery with pagination | `follow_pagination: true` |
| Whole site | `site_discovery: true, crawl_depth: 5, follow_links: true, max_pages: 10000` |
| JavaScript app | `use_browser: true, max_scrolls: 50` |
| Video / stream | `use_browser: true, file_types: ["mp4", "m3u8", "mpd"]` |

---

## Decryptors

Applied in priority order; the first whose `can_handle()` accepts the content
processes it. The pipeline runs up to three passes.

| Decryptor | Priority | Configuration |
|---|---|---|
| Base64 | 10 | — |
| Hex | 10 | — |
| AES | 20 | `key` (hex), `iv` (hex), `mode` (CBC/ECB/GCM) |
| XOR | 30 | `key` (hex) |
| URL sign strip | 40 | — |
| ROT47 | 50 | — |
| Custom | 100 | Python expression over `content` |

> **Custom expressions run unsandboxed** in the server process, by design. Only
> use them on a machine you control.

---

## Project layout

```
Auto-Get-PY/
├── app.py                      # FastAPI entry point, router mounting, CLI
├── mcp_server.py               # dependency-free MCP stdio server
├── scraper/
│   ├── engine.py               # orchestration: discovery, then transfer
│   ├── extractor.py            # every URL-discovery strategy + URL normalisation
│   ├── downloader.py           # transfer: plain files, HLS, DASH, resume
│   ├── site_crawler.py         # robots.txt, sitemaps, feeds
│   ├── browser.py              # Playwright rendering and network capture
│   ├── task_manager.py         # lifecycle: start/pause/resume/cancel/retry
│   └── decryptors/             # pluggable decoding pipeline
├── api/
│   ├── agent.py                # canonical agent API (mounted under every alias)
│   ├── agent_registry.py       # the table of supported tools
│   ├── agent_docs.py           # renders skills/manifest from the registry
│   ├── tasks.py downloads.py settings.py files.py websocket.py
├── db/
│   ├── schema.py               # schema + in-place migrations
│   └── queries.py              # all SQL lives here
├── webui/
│   ├── index.html
│   ├── css/style.css           # design system (light + dark)
│   └── js/                     # ES modules, no build step
│       ├── i18n.js  locales.js # translation runtime + zh/en dictionaries
│       ├── core.js api.js ws.js live.js router.js
│       └── pages/              # dashboard, new-task, downloads, files, agents, settings
├── scripts/
│   ├── generate_agent_docs.py  # writes every agent config + doc
│   ├── serve_test_site.py      # the fixture site, for manual testing
│   └── check_ui.py             # headless-browser UI check
├── mcp_server.py               # dependency-free MCP stdio server
├── tests/                      # 160 tests, incl. a full local test website
└── docs/agents/                # generated per-tool integration guides
```

---

## Development

```bash
pip install -r requirements.txt pytest pytest-asyncio

python -m pytest tests/ -q                    # 160 tests
python scripts/generate_agent_docs.py --check # generated files are current
```

The end-to-end tests run against `tests/local_site.py`, a real aiohttp site
covering cookies, hotlink protection, HLS, flaky endpoints, pagination, feeds
and sitemaps — no internet access required. To poke at it by hand:

```bash
python scripts/serve_test_site.py --port 9911
python app.py
```

Optional front-end checks:

```bash
# Fast: load the SPA in a DOM and drive every page (needs Node + jsdom)
node webui/tests/smoke.mjs

# Thorough: drive the SPA in headless Chromium against a running server
python scripts/check_ui.py --base-url http://127.0.0.1:8765
```

---

## Limits

This is a **local, single-user** tool. Deliberately not included:

- Multi-user accounts or per-user isolation
- Distributed crawling (Celery/Redis)
- CAPTCHA solving
- A sandbox for custom decryptor expressions

Please respect the terms of service of the sites you scrape, and keep
`request_delay_sec` sensible.

---

## Licence

MIT

---

[中文版文档 (Chinese)](README_CN.md)
