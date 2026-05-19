# Web Scraper + Media Downloader Design Spec

## Overview

A Python-based universal web scraper with media download capability and a local Web UI management frontend. Supports multi-layer decryption, concurrent downloads, task persistence, and resume capability — all accessible through a single-command launch.

## Scope

- Python FastAPI backend with async I/O
- Pluggable decryptor pipeline (AES, Base64, XOR, URL sign, etc.)
- Universal media file downloader (image, video, audio, document, archive)
- Local Web UI served by the same process (localhost:8000)
- SQLite persistence for tasks, downloads, and settings
- Single user, localhost only

## Tech Stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12, FastAPI, aiohttp, aiofiles, aiosqlite |
| Frontend | HTML/CSS/JS (produced by frontend-design skill) |
| Database | SQLite |
| Real-time | WebSocket (FastAPI built-in) |
| Packaging | requirements.txt, single entry `app.py` |

## Architecture

```
Browser (localhost:8000/webui)
       │ HTTP REST + WebSocket
       ▼
FastAPI App
  ├── REST API (/api/*)
  ├── WebSocket (/ws/progress)
  ├── Static Files (/webui/*)
  ├── Task Manager (queue, lifecycle, concurrency control)
  ├── Scraper Engine
  │     ├── URL Extractor (parse HTML/JS for media links)
  │     ├── Decryptor Pipeline (pluggable, priority-ordered)
  │     └── Download Worker Pool (asyncio semaphore)
  └── SQLite (tasks, downloads, settings)
```

## Database Schema

```sql
CREATE TABLE tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    status      TEXT DEFAULT 'pending',  -- pending|running|paused|completed|failed
    config      TEXT DEFAULT '{}',       -- JSON
    total_files INTEGER DEFAULT 0,
    done_files  INTEGER DEFAULT 0,
    error_msg   TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    filename    TEXT,
    file_size   INTEGER DEFAULT 0,
    downloaded  INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'pending',  -- pending|downloading|completed|failed|skipped
    retry_count INTEGER DEFAULT 0,
    error_msg   TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

## Task Config Schema

```json
{
  "concurrency": 5,
  "output_dir": "./downloads",
  "decryptors": ["base64", "aes"],
  "decryptor_opts": {
    "aes": {"key": "", "iv": "", "mode": "cbc"}
  },
  "url_filters": {
    "include": ["*.jpg", "*.mp4", "*.pdf"],
    "exclude": ["*.gif"]
  },
  "custom_headers": {},
  "crawl_depth": 1,
  "request_delay_sec": 0.5,
  "request_timeout_sec": 30,
  "max_retries": 3,
  "max_file_size_mb": 500
}
```

## API Routes

```
GET    /api/tasks              # List tasks (paginated, filterable by status)
POST   /api/tasks              # Create a new task
GET    /api/tasks/{id}         # Get task detail
PUT    /api/tasks/{id}         # Update task config
DELETE /api/tasks/{id}         # Delete task and cascade downloads
POST   /api/tasks/{id}/start   # Start scraping
POST   /api/tasks/{id}/pause   # Pause
POST   /api/tasks/{id}/resume  # Resume
POST   /api/tasks/{id}/retry   # Retry all failed downloads

GET    /api/tasks/{id}/downloads  # List downloads for a task

GET    /api/settings           # Get all settings
PUT    /api/settings           # Update settings

GET    /api/files              # Browse downloaded files
GET    /api/files/download/{filename}  # Serve file for local download

WS     /ws/progress            # Real-time: {task_id, done, total, download_speed, current_file}
```

## Decryptor Plugin System

### Base Class

```python
class BaseDecryptor(ABC):
    name: str
    priority: int  # Lower = runs first in pipeline

    @abstractmethod
    async def can_handle(self, content: bytes, context: dict) -> bool: ...

    @abstractmethod
    async def decrypt(self, content: bytes, context: dict) -> bytes: ...
```

### Built-in Decryptors

| Name | Priority | Description |
|------|----------|-------------|
| Base64Decoder | 10 | Standard Base64 decode |
| HexDecoder | 10 | Hexadecimal to bytes |
| AESDecoder | 20 | AES-ECB/CBC/GCM with configurable key/IV |
| XORDecoder | 30 | Single/multi-byte XOR |
| URLSignDecoder | 40 | Strip URL signing params (expires, sign, token) |
| Rot47Decoder | 50 | ROT13/ROT47 character shift |
| CustomExprDecoder | 100 | User-supplied Python expression in UI |

### Pipeline Logic

1. Content enters pipeline
2. Decryptors sorted by priority, filtered by user enablement
3. Each decryptor's `can_handle()` tested; first match wins
4. `decrypt()` transforms content; result may re-enter pipeline (configurable max passes)
5. If no decryptor matches, content passes through unchanged

## Frontend Pages

### Dashboard
- Stat cards: running / completed / failed task counts
- Live progress bars (WebSocket-driven) for active tasks
- Recent completed tasks table

### New Task
- URL input + task name
- Decryptor checkboxes with expandable config panels (AES key/IV fields, etc.)
- File type filters: preset checkboxes grouped by category (image/video/audio/doc/archive) + custom field
- Advanced options: concurrency, request delay, crawl depth, custom headers (key-value editor)

### Downloads
- Filterable by task
- Table: filename, size, status badge, progress bar, time
- Search and column sort
- Batch actions: retry failed, delete selected, export list

### Settings
- Default concurrency, download directory
- Default decryptor selections
- AES key management

## Project File Structure

```
project-SIMC/
├── app.py                         # FastAPI entry point, serve static + mount routers
├── scraper/
│   ├── __init__.py
│   ├── engine.py                  # Orchestrator: extract → decrypt → download
│   ├── extractor.py               # Media URL extraction from HTML/text
│   ├── downloader.py              # Async chunked download with resume and progress
│   ├── task_manager.py            # Task lifecycle, concurrency semaphore
│   └── decryptors/
│       ├── __init__.py            # Decryptor registry + pipeline runner
│       ├── base.py                # BaseDecryptor ABC
│       ├── base64_dec.py
│       ├── hex_dec.py
│       ├── aes_dec.py
│       ├── xor_dec.py
│       ├── url_sign_dec.py
│       ├── rot47_dec.py
│       └── custom_dec.py
├── db/
│   ├── __init__.py
│   ├── schema.py                  # CREATE TABLE statements
│   └── queries.py                 # Async query functions
├── api/
│   ├── __init__.py
│   ├── tasks.py                   # Task CRUD + control endpoints
│   ├── downloads.py               # Download list endpoints
│   ├── settings.py                # Settings endpoints
│   ├── files.py                   # File browsing + serving
│   └── websocket.py              # Progress WebSocket handler
├── webui/                         # Frontend static files
│   ├── index.html
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── app.js                 # SPA router, init
│       ├── api.js                 # REST + WebSocket client
│       ├── dashboard.js
│       ├── task-form.js
│       ├── downloads.js
│       └── settings.js
├── downloads/                     # Default output directory
└── requirements.txt
```

## Key Behaviors

### Concurrency
- Global semaphore limits total concurrent downloads across all tasks
- Per-task concurrency configurable via `config.concurrency`
- Default: 5 concurrent, max: 20

### Resume
- Downloads track `downloaded` bytes in DB
- HTTP Range header for resume on supported servers
- Unsupported servers: restart from 0

### Error Handling
- Per-file retry with exponential backoff (1s, 2s, 4s, ..., capped at 60s)
- Max retries configurable per task
- Task continues on individual file failure
- Task marks `failed` only if all files fail or if page fetch fails

### Pause / Resume
- Pause: in-flight downloads complete current chunk, then workers yield. All state (downloaded bytes, status) committed to DB
- Resume: reloads task config from DB, re-enqueues pending/interrupted downloads, workers pick up from last checkpoint

### Shutdown
- Graceful: pause all active downloads, commit state to DB
- On restart: resume `running` and `paused` tasks (user choice in UI)

## Testing Strategy

- Unit tests for each decryptor (known ciphertext → plaintext)
- Unit tests for URL extractor (sample HTML pages)
- Integration tests for API endpoints (FastAPI TestClient)
- Integration tests for task lifecycle (create → start → pause → resume → complete)
- Async mock for aiohttp to test downloader without network

## Out of Scope

- Authentication / multi-user
- Distributed crawling (Celery, Redis)
- Browser automation (Playwright/Selenium for JS-rendered pages)
- OCR-based decryption (captcha)
- Custom Python expression sandboxing — user expressions run in-process, trust assumed for local-only usage
- Docker packaging
