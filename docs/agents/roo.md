# Auto-Get-PY integration — Roo Code

> Generated from `api/agent_registry.py` — do not edit by hand.
> Refresh with `python scripts/generate_agent_docs.py`.

**Vendor:** Roo
**URL alias:** `/api/roo` (canonical: `/api/agent`)
**Config files written:** `.roo/rules/auto-get-py.md`, `.roo/mcp.json`

## Setup

Roo Code reads `.roo/rules/` and `.roo/mcp.json`.

## How to install it

1. Clone this repository and install the dependencies:

   ```bash
   pip install -r requirements.txt
   python app.py
   ```

2. Confirm the service is up: `curl http://localhost:8000/api/health`

3. Make the agent aware of the API — either:

   - commit/keep `.roo/rules/auto-get-py.md` (already generated in this repo), or
   - commit/keep `.roo/mcp.json` (already generated in this repo), or
   - paste the contents of the skill document at `http://localhost:8000/api/agent/skill?agent=roo`

4. Optional: for JS-heavy targets run `playwright install chromium`.

## What this service does

`Auto-Get-PY` is a local, self-hosted media scraper. It takes a URL, finds
every downloadable asset reachable from it, and writes them to disk.

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

## Base URL

```
http://localhost:8000
```

All endpoints below are relative to `/api/roo`. The service must be running:
start it with `python app.py` inside the `Auto-Get-PY` checkout. Check
`GET http://localhost:8000/api/roo/health` first — it returns `{"status": "ok"}`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/roo/scrape` | Crawl a page/site and download everything found. Returns a `task_id`, or the final result when `wait=true`. |
| `POST` | `/api/roo/quick` | Discover media URLs only — nothing is written to disk. Use this to preview before downloading. |
| `POST` | `/api/roo/direct` | Playwright render + immediate download, synchronous. Best for single JS-heavy pages. |
| `POST` | `/api/roo/fetch` | Download one exact URL. No crawling. |
| `GET` | `/api/roo/status/{task_id}` | Progress, per-status download counts, error. |
| `GET` | `/api/roo/results/{task_id}` | Final file list with paths and sizes. |
| `POST` | `/api/roo/cancel/{task_id}` | Stop a running task and free its workers. |
| `GET` | `/api/roo/tasks` | Recent tasks. |
| `GET` | `/api/roo/files` | Files on disk, newest first. |
| `GET` | `/api/roo/manifest` | Machine-readable capability + endpoint manifest. |
| `GET` | `/api/roo/agents` | Every supported agent and its URL alias. |
| `GET` | `/api/roo/skill` | This document, served as markdown (`?agent=<id>`). |

## Response shapes

`POST /scrape` with `wait: false`:

```json
{
  "task_id": 7,
  "status": "running",
  "status_url": "/api/roo/status/7",
  "results_url": "/api/roo/results/7"
}
```

`GET /status/{id}`:

```json
{
  "task_id": 7,
  "status": "running",
  "progress": 42.5,
  "total_files": 120,
  "done_files": 51,
  "downloads": {"pending": 60, "downloading": 5, "completed": 51,
                "failed": 4, "total": 120, "bytes": 81234567},
  "pages_crawled": 18,
  "total_media_found": 120,
  "error_msg": null
}
```

`GET /results/{id}`:

```json
{
  "task_id": 7,
  "status": "completed",
  "output_dir": "./downloads",
  "stats": {"total_files": 120, "completed": 116, "failed": 4,
            "total_size_bytes": 81234567, "pages_crawled": 18},
  "completed_files": [
    {"filename": "photo-01.jpg", "url": "https://…", "size_bytes": 204800,
      "filepath": "./downloads/photo-01.jpg", "mime_type": "image/jpeg"}
  ],
  "failed_files": [{"filename": "x.mp4", "url": "https://…", "error": "HTTP 403"}]
}
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
5. **Track** — poll `GET /status/{id}` every few seconds and report progress.
6. **Report** — `GET /results/{id}`, then summarise: how many files, where
   they are, what failed and why.

## Scenario templates

### Image gallery

```bash
curl -s http://localhost:8000/api/roo/quick \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/gallery/", "crawl_depth": 2, "follow_pagination": true, "file_types": ["jpg", "png", "webp"]}'
```

```json
{
  "url": "https://example.com/gallery/",
  "crawl_depth": 2,
  "follow_pagination": true,
  "file_types": [
    "jpg",
    "png",
    "webp"
  ]
}
```

### Video page

```bash
curl -s http://localhost:8000/api/roo/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/watch/123", "use_browser": true, "file_types": ["mp4", "m3u8", "webm"]}'
```

```json
{
  "url": "https://example.com/watch/123",
  "use_browser": true,
  "file_types": [
    "mp4",
    "m3u8",
    "webm"
  ]
}
```

### Full site mirror

```bash
curl -s http://localhost:8000/api/roo/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/", "site_discovery": true, "crawl_depth": 5, "max_pages": 10000, "follow_links": true, "follow_pagination": true}'
```

```json
{
  "url": "https://example.com/",
  "site_discovery": true,
  "crawl_depth": 5,
  "max_pages": 10000,
  "follow_links": true,
  "follow_pagination": true
}
```

### JavaScript SPA

```bash
curl -s http://localhost:8000/api/roo/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/", "use_browser": true, "crawl_depth": 3, "max_scrolls": 50}'
```

```json
{
  "url": "https://example.com/",
  "use_browser": true,
  "crawl_depth": 3,
  "max_scrolls": 50
}
```

### Behind a proxy

```bash
curl -s http://localhost:8000/api/roo/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/", "proxy": "http://127.0.0.1:7890", "crawl_depth": 2}'
```

```json
{
  "url": "https://example.com/",
  "proxy": "http://127.0.0.1:7890",
  "crawl_depth": 2
}
```

### Login-gated / hotlink-protected

```bash
curl -s http://localhost:8000/api/roo/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/", "crawl_css": true, "crawl_iframes": true, "custom_headers": {"Cookie": "session=...", "Referer": "https://example.com/"}}'
```

```json
{
  "url": "https://example.com/",
  "crawl_css": true,
  "crawl_iframes": true,
  "custom_headers": {
    "Cookie": "session=...",
    "Referer": "https://example.com/"
  }
}
```

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
| `decryptor_opts` | object | `null` | e.g. `{"aes": {"key": "…hex…", "iv": "…hex…"}}` |
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


## Roo Code specifics

- This tool can reach the API at `/api/roo` — identical responses to `/api/agent`.
- Canonical prefix: `/api/agent`.
- Files provided for this tool: `.roo/rules/auto-get-py.md`, `.roo/mcp.json`.
- Roo Code documentation: https://docs.roocode.com/
