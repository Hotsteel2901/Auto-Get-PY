# Web Scraper + Media Downloader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python FastAPI-based web scraper with pluggable decryptors, async media downloader, and a local Web UI management frontend.

**Architecture:** FastAPI monolith serving REST API (/api/*), WebSocket (/ws/progress), and static frontend files (/webui/*). Async scraper engine with extractor → decryptor pipeline → download worker pool. SQLite persistence via aiosqlite.

**Tech Stack:** Python 3.12, FastAPI, aiohttp, aiofiles, aiosqlite, native HTML/CSS/JS frontend

**Note for frontend tasks (16-20):** Invoke the `frontend-design:frontend-design` skill before writing any frontend code.

---

## Phase 1: Foundation

### Task 1: Project skeleton and dependencies

**Files:**
- Create: `requirements.txt`
- Create: `scraper/__init__.py`
- Create: `db/__init__.py`
- Create: `api/__init__.py`
- Create: `app.py` (minimal skeleton)
- Create: `downloads/.gitkeep`

- [ ] **Step 1: Write requirements.txt**

```txt
fastapi==0.115.6
uvicorn[standard]==0.34.0
aiohttp==3.11.11
aiofiles==24.1.0
aiosqlite==0.20.0
pydantic==2.10.4
```

- [ ] **Step 2: Create directory structure and empty __init__.py files**

Run:
```bash
mkdir -p /root/project-SIMC/{scraper/decryptors,db,api,webui/{css,js},downloads,tests}
touch /root/project-SIMC/scraper/__init__.py
touch /root/project-SIMC/db/__init__.py
touch /root/project-SIMC/api/__init__.py
touch /root/project-SIMC/tests/__init__.py
touch /root/project-SIMC/downloads/.gitkeep
```

- [ ] **Step 3: Write minimal app.py skeleton**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    from db.schema import init_db
    await init_db()
    yield


app = FastAPI(title="Web Scraper", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Install dependencies and verify startup**

Run:
```bash
cd /root/project-SIMC && pip install -r requirements.txt
cd /root/project-SIMC && timeout 5 python -c "from app import app; print('Import OK')" 2>&1
```
Expected: `Import OK`

- [ ] **Step 5: Commit**

```bash
cd /root/project-SIMC && git init && git add -A && git commit -m "feat: project skeleton with FastAPI entry point and dependencies"
```

---

### Task 2: Database schema and initialization

**Files:**
- Create: `db/schema.py`

- [ ] **Step 1: Write schema.py with init_db()**

```python
import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "scraper.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    status      TEXT DEFAULT 'pending',
    config      TEXT DEFAULT '{}',
    total_files INTEGER DEFAULT 0,
    done_files  INTEGER DEFAULT 0,
    error_msg   TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    filename    TEXT,
    file_size   INTEGER DEFAULT 0,
    downloaded  INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    error_msg   TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

INSERT OR IGNORE INTO settings (key, value) VALUES
    ('default_concurrency', '5'),
    ('default_output_dir', './downloads'),
    ('default_decryptors', '["base64","hex"]');
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    await db.executescript(SCHEMA_SQL)
    await db.commit()
    await db.close()
```

- [ ] **Step 2: Verify init_db works**

Run:
```bash
cd /root/project-SIMC && python -c "
import asyncio
from db.schema import init_db, DB_PATH
asyncio.run(init_db())
import sqlite3
conn = sqlite3.connect(str(DB_PATH))
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print('Tables:', tables)
conn.close()
"
```
Expected output shows `tasks`, `downloads`, `settings` tables and the `scraper.db` file exists.

- [ ] **Step 3: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: database schema with SQLite init and WAL mode"
```

---

### Task 3: Database query layer

**Files:**
- Create: `db/queries.py`

- [ ] **Step 1: Write queries.py**

```python
from db.schema import get_db
import json


# --- Tasks ---

async def create_task(name: str, url: str, config: dict = None) -> dict:
    db = await get_db()
    cur = await db.execute(
        "INSERT INTO tasks (name, url, config) VALUES (?, ?, ?)",
        (name, url, json.dumps(config or {})),
    )
    await db.commit()
    task_id = cur.lastrowid
    row = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    result = await row.fetchone()
    await db.close()
    return dict(result)


async def list_tasks(status: str = None, offset: int = 0, limit: int = 20) -> list[dict]:
    db = await get_db()
    if status:
        rows = await db.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
    else:
        rows = await db.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    results = [dict(r) for r in await rows.fetchall()]
    await db.close()
    return results


async def get_task(task_id: int) -> dict | None:
    db = await get_db()
    row = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    result = await row.fetchone()
    await db.close()
    return dict(result) if result else None


async def update_task(task_id: int, **kwargs) -> dict | None:
    if not kwargs:
        return await get_task(task_id)
    db = await get_db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [task_id]
    await db.execute(f"UPDATE tasks SET {sets}, updated_at = datetime('now') WHERE id = ?", vals)
    await db.commit()
    row = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    result = await row.fetchone()
    await db.close()
    return dict(result) if result else None


async def delete_task(task_id: int) -> bool:
    db = await get_db()
    cur = await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    await db.commit()
    deleted = cur.rowcount > 0
    await db.close()
    return deleted


# --- Downloads ---

async def create_download(task_id: int, url: str, filename: str = None) -> dict:
    db = await get_db()
    cur = await db.execute(
        "INSERT INTO downloads (task_id, url, filename) VALUES (?, ?, ?)",
        (task_id, url, filename),
    )
    await db.commit()
    dl_id = cur.lastrowid
    row = await db.execute("SELECT * FROM downloads WHERE id = ?", (dl_id,))
    result = await row.fetchone()
    await db.close()
    return dict(result)


async def list_downloads(task_id: int, status: str = None) -> list[dict]:
    db = await get_db()
    if status:
        rows = await db.execute(
            "SELECT * FROM downloads WHERE task_id = ? AND status = ? ORDER BY created_at DESC",
            (task_id, status),
        )
    else:
        rows = await db.execute(
            "SELECT * FROM downloads WHERE task_id = ? ORDER BY created_at DESC",
            (task_id,),
        )
    results = [dict(r) for r in await rows.fetchall()]
    await db.close()
    return results


async def update_download(dl_id: int, **kwargs) -> dict | None:
    if not kwargs:
        return None
    db = await get_db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [dl_id]
    await db.execute(f"UPDATE downloads SET {sets} WHERE id = ?", vals)
    await db.commit()
    row = await db.execute("SELECT * FROM downloads WHERE id = ?", (dl_id,))
    result = await row.fetchone()
    await db.close()
    return dict(result) if result else None


async def count_downloads_by_status(task_id: int, status: str) -> int:
    db = await get_db()
    row = await db.execute(
        "SELECT COUNT(*) as cnt FROM downloads WHERE task_id = ? AND status = ?",
        (task_id, status),
    )
    result = await row.fetchone()
    await db.close()
    return result["cnt"] if result else 0


async def get_failed_downloads(task_id: int) -> list[dict]:
    db = await get_db()
    rows = await db.execute(
        "SELECT * FROM downloads WHERE task_id = ? AND status = 'failed'",
        (task_id,),
    )
    results = [dict(r) for r in await rows.fetchall()]
    await db.close()
    return results


# --- Settings ---

async def get_settings() -> dict:
    db = await get_db()
    rows = await db.execute("SELECT key, value FROM settings")
    results = {r["key"]: r["value"] for r in await rows.fetchall()}
    await db.close()
    return results


async def update_setting(key: str, value: str):
    db = await get_db()
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, value, value),
    )
    await db.commit()
    await db.close()
```

- [ ] **Step 2: Verify queries with a quick smoke test**

Run:
```bash
cd /root/project-SIMC && python -c "
import asyncio
from db.schema import init_db
from db import queries as q

async def test():
    await init_db()
    t = await q.create_task('test', 'http://example.com', {'concurrency': 3})
    print('Created task:', t['id'])
    tasks = await q.list_tasks()
    print('Task count:', len(tasks))
    d = await q.create_download(t['id'], 'http://example.com/img.jpg', 'img.jpg')
    print('Created download:', d['id'])
    dls = await q.list_downloads(t['id'])
    print('Download count:', len(dls))
    await q.update_download(d['id'], status='completed', file_size=1024)
    s = await q.get_settings()
    print('Settings:', s)
    await q.delete_task(t['id'])
    print('OK')

asyncio.run(test())
"
```
Expected: prints task ID, download ID, counts, settings, and "OK".

- [ ] **Step 3: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: async database query layer for tasks, downloads, and settings"
```

---

## Phase 2: Decryptor System

### Task 4: Base decryptor class and registry

**Files:**
- Create: `scraper/decryptors/base.py`
- Create: `scraper/decryptors/__init__.py`

- [ ] **Step 1: Write base.py**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DecryptorResult:
    success: bool
    data: bytes
    decryptor_name: str = ""


class BaseDecryptor(ABC):
    name: str = "base"
    priority: int = 50

    @abstractmethod
    async def can_handle(self, content: bytes, context: dict) -> bool:
        ...

    @abstractmethod
    async def decrypt(self, content: bytes, context: dict) -> bytes:
        ...


_registry: list[BaseDecryptor] = []


def register(dec: BaseDecryptor):
    _registry.append(dec)


def get_enabled_decryptors(enabled_names: list[str]) -> list[BaseDecryptor]:
    filtered = [d for d in _registry if d.name in enabled_names]
    filtered.sort(key=lambda d: d.priority)
    return filtered


async def run_pipeline(content: bytes, enabled_names: list[str], context: dict,
                       max_passes: int = 3) -> DecryptorResult:
    decryptors = get_enabled_decryptors(enabled_names)
    current = content
    for _ in range(max_passes):
        handled = False
        for dec in decryptors:
            if await dec.can_handle(current, context):
                current = await dec.decrypt(current, context)
                handled = True
                break
        if not handled:
            break
    return DecryptorResult(success=True, data=current)
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: decryptor base class with registry and pipeline runner"
```

---

### Task 5: Simple decryptors (Base64, Hex, Rot47)

**Files:**
- Create: `scraper/decryptors/base64_dec.py`
- Create: `scraper/decryptors/hex_dec.py`
- Create: `scraper/decryptors/rot47_dec.py`
- Create: `tests/test_decryptors_simple.py`

- [ ] **Step 1: Write failing tests for simple decryptors**

```python
import pytest
import asyncio
from scraper.decryptors.base64_dec import Base64Decoder
from scraper.decryptors.hex_dec import HexDecoder
from scraper.decryptors.rot47_dec import Rot47Decoder
from scraper.decryptors import register, run_pipeline


@pytest.mark.asyncio
async def test_base64_can_handle():
    dec = Base64Decoder()
    assert await dec.can_handle(b"SGVsbG8gV29ybGQ=", {}) is True
    assert await dec.can_handle(b"\xff\xfe\x00\x01", {}) is False


@pytest.mark.asyncio
async def test_base64_decrypt():
    dec = Base64Decoder()
    result = await dec.decrypt(b"SGVsbG8gV29ybGQ=", {})
    assert result == b"Hello World"


@pytest.mark.asyncio
async def test_hex_can_handle():
    dec = HexDecoder()
    assert await dec.can_handle(b"48656c6c6f", {}) is True
    assert await dec.can_handle(b"hello world", {}) is False


@pytest.mark.asyncio
async def test_hex_decrypt():
    dec = HexDecoder()
    result = await dec.decrypt(b"48656c6c6f", {})
    assert result == b"Hello"


@pytest.mark.asyncio
async def test_rot47_roundtrip():
    dec = Rot47Decoder()
    original = b"Hello World 123!"
    encoded = await dec.decrypt(original, {})
    decoded = await dec.decrypt(encoded, {})
    assert decoded == original
    assert encoded != original


@pytest.mark.asyncio
async def test_pipeline_with_base64():
    from scraper.decryptors.base import _registry
    _registry.clear()
    register(Base64Decoder())
    register(HexDecoder())
    result = await run_pipeline(b"SGVsbG8gV29ybGQ=", ["base64", "hex"], {})
    assert result.data == b"Hello World"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/project-SIMC && python -m pytest tests/test_decryptors_simple.py -v`
Expected: ModuleNotFoundError (files don't exist yet)

- [ ] **Step 3: Write base64_dec.py**

```python
import base64
import re
from scraper.decryptors.base import BaseDecryptor


class Base64Decoder(BaseDecryptor):
    name = "base64"
    priority = 10

    async def can_handle(self, content: bytes, context: dict) -> bool:
        try:
            text = content.decode("ascii", errors="ignore").strip()
            return bool(re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", text)) and len(text) >= 4
        except Exception:
            return False

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        text = content.decode("ascii", errors="ignore").strip()
        padding = 4 - len(text) % 4
        if padding != 4:
            text += "=" * padding
        return base64.b64decode(text)
```

- [ ] **Step 4: Write hex_dec.py**

```python
import re
from scraper.decryptors.base import BaseDecryptor


class HexDecoder(BaseDecryptor):
    name = "hex"
    priority = 10

    async def can_handle(self, content: bytes, context: dict) -> bool:
        try:
            text = content.decode("ascii", errors="ignore").strip()
            return bool(re.fullmatch(r"([0-9a-fA-F]{2})+", text)) and len(text) >= 4
        except Exception:
            return False

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        text = content.decode("ascii", errors="ignore").strip()
        return bytes.fromhex(text)
```

- [ ] **Step 5: Write rot47_dec.py**

```python
from scraper.decryptors.base import BaseDecryptor


class Rot47Decoder(BaseDecryptor):
    name = "rot47"
    priority = 50

    async def can_handle(self, content: bytes, context: dict) -> bool:
        try:
            text = content.decode("ascii", errors="ignore")
            printable = sum(1 for c in text if 33 <= ord(c) <= 126)
            return printable / max(len(text), 1) > 0.8
        except Exception:
            return False

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        result = []
        for b in content:
            if 33 <= b <= 126:
                result.append(33 + ((b - 33 + 47) % 94))
            else:
                result.append(b)
        return bytes(result)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /root/project-SIMC && python -m pytest tests/test_decryptors_simple.py -v`
Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: Base64, Hex, and Rot47 decryptors with tests"
```

---

### Task 6: Complex decryptors (AES, XOR, URLSign, CustomExpr)

**Files:**
- Create: `scraper/decryptors/aes_dec.py`
- Create: `scraper/decryptors/xor_dec.py`
- Create: `scraper/decryptors/url_sign_dec.py`
- Create: `scraper/decryptors/custom_dec.py`
- Create: `tests/test_decryptors_complex.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from scraper.decryptors.aes_dec import AESDecoder
from scraper.decryptors.xor_dec import XORDecoder
from scraper.decryptors.url_sign_dec import URLSignDecoder
from scraper.decryptors.custom_dec import CustomExprDecoder


@pytest.mark.asyncio
async def test_aes_can_handle_with_key():
    dec = AESDecoder()
    ctx = {"aes_key": "0123456789abcdef0123456789abcdef"}
    assert await dec.can_handle(b"anything", ctx) is True


@pytest.mark.asyncio
async def test_aes_can_handle_without_key():
    dec = AESDecoder()
    assert await dec.can_handle(b"anything", {}) is False


@pytest.mark.asyncio
async def test_aes_cbc_decrypt():
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    key = b"0123456789abcdef0123456789abcdef"
    iv = b"0123456789abcdef"
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = b"Hello Secret World!!!"
    ciphertext = cipher.encrypt(pad(plaintext, 16))
    ctx = {"aes_key": key.hex(), "aes_iv": iv.hex(), "aes_mode": "cbc"}
    dec = AESDecoder()
    result = await dec.decrypt(ciphertext, ctx)
    assert result == plaintext


@pytest.mark.asyncio
async def test_xor_single_byte():
    dec = XORDecoder()
    ctx = {"xor_key": "55"}
    ciphertext = bytes(b ^ 0x55 for b in b"Hello")
    result = await dec.decrypt(ciphertext, ctx)
    assert result == b"Hello"


@pytest.mark.asyncio
async def test_url_sign_strip():
    dec = URLSignDecoder()
    content = b"http://example.com/file.jpg?sign=abc123&expires=99999&token=xyz"
    result = await dec.decrypt(content, {})
    assert b"sign=" not in result
    assert result == b"http://example.com/file.jpg"


@pytest.mark.asyncio
async def test_custom_expr():
    dec = CustomExprDecoder()
    ctx = {"custom_expr": "bytes(b ^ 0xFF for b in content)"}
    content = bytes(b ^ 0xFF for b in b"Hello")
    result = await dec.decrypt(content, ctx)
    assert result == b"Hello"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/project-SIMC && python -m pytest tests/test_decryptors_complex.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Write aes_dec.py**

```python
from scraper.decryptors.base import BaseDecryptor


class AESDecoder(BaseDecryptor):
    name = "aes"
    priority = 20

    async def can_handle(self, content: bytes, context: dict) -> bool:
        return bool(context.get("aes_key"))

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad

        key = bytes.fromhex(context["aes_key"])
        mode = context.get("aes_mode", "cbc").upper()
        iv = bytes.fromhex(context.get("aes_iv", "00" * 16))

        if mode == "ECB":
            cipher = AES.new(key, AES.MODE_ECB)
        elif mode == "GCM":
            cipher = AES.new(key, AES.MODE_GCM, nonce=iv[:16])
            return cipher.decrypt_and_verify(content[:-16], content[-16:])
        else:
            cipher = AES.new(key, AES.MODE_CBC, iv)

        try:
            return unpad(cipher.decrypt(content), 16)
        except Exception:
            return cipher.decrypt(content)
```

- [ ] **Step 4: Write xor_dec.py**

```python
from scraper.decryptors.base import BaseDecryptor


class XORDecoder(BaseDecryptor):
    name = "xor"
    priority = 30

    async def can_handle(self, content: bytes, context: dict) -> bool:
        return bool(context.get("xor_key"))

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        key = bytes.fromhex(context["xor_key"])
        return bytes(content[i] ^ key[i % len(key)] for i in range(len(content)))
```

- [ ] **Step 5: Write url_sign_dec.py**

```python
import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from scraper.decryptors.base import BaseDecryptor


class URLSignDecoder(BaseDecryptor):
    name = "url_sign"
    priority = 40

    SIGN_PARAMS = {"sign", "signature", "token", "expires", "expire", "timestamp", "ts", "nonce", "auth", "auth_key", "access_token"}

    async def can_handle(self, content: bytes, context: dict) -> bool:
        try:
            text = content.decode("ascii", errors="ignore")
            parsed = urlparse(text)
            return any(p in parsed.query.lower() for p in self.SIGN_PARAMS)
        except Exception:
            return False

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        text = content.decode("ascii", errors="ignore")
        parsed = urlparse(text)
        params = parse_qs(parsed.query, keep_blank_values=True)
        extra = set(context.get("url_sign_extra_params", "").split(",")) if context.get("url_sign_extra_params") else set()
        strip_params = self.SIGN_PARAMS | {p.strip().lower() for p in extra if p.strip()}

        cleaned = {k: v for k, v in params.items() if k.lower() not in strip_params}
        new_query = urlencode(cleaned, doseq=True)
        new_parsed = parsed._replace(query=new_query)
        return urlunparse(new_parsed).encode("ascii")
```

- [ ] **Step 6: Write custom_dec.py**

```python
from scraper.decryptors.base import BaseDecryptor


class CustomExprDecoder(BaseDecryptor):
    name = "custom"
    priority = 100

    async def can_handle(self, content: bytes, context: dict) -> bool:
        return bool(context.get("custom_expr"))

    async def decrypt(self, content: bytes, context: dict) -> bytes:
        expr = context["custom_expr"]
        local_vars = {"content": content, "bytes": bytes}
        result = eval(expr, {"__builtins__": {}}, local_vars)
        if isinstance(result, str):
            return result.encode("utf-8")
        return bytes(result)
```

- [ ] **Step 7: Register all decryptors in decryptors/__init__.py**

Update `scraper/decryptors/__init__.py` to import all decryptors after the base definitions:

```python
from scraper.decryptors.base import BaseDecryptor, DecryptorResult, register, get_enabled_decryptors, run_pipeline

from scraper.decryptors.base64_dec import Base64Decoder
from scraper.decryptors.hex_dec import HexDecoder
from scraper.decryptors.rot47_dec import Rot47Decoder
from scraper.decryptors.aes_dec import AESDecoder
from scraper.decryptors.xor_dec import XORDecoder
from scraper.decryptors.url_sign_dec import URLSignDecoder
from scraper.decryptors.custom_dec import CustomExprDecoder


def register_all():
    register(Base64Decoder())
    register(HexDecoder())
    register(Rot47Decoder())
    register(AESDecoder())
    register(XORDecoder())
    register(URLSignDecoder())
    register(CustomExprDecoder())
```

- [ ] **Step 8: Add pycryptodome to requirements.txt**

Edit `requirements.txt`, append:
```
pycryptodome==3.21.0
```

And install:
```bash
cd /root/project-SIMC && pip install pycryptodome
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd /root/project-SIMC && python -m pytest tests/test_decryptors_complex.py -v`
Expected: 6 passed

- [ ] **Step 10: Run all decryptor tests**

Run: `cd /root/project-SIMC && python -m pytest tests/ -v`
Expected: 12 passed

- [ ] **Step 11: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: AES, XOR, URLSign, and CustomExpr decryptors with tests"
```

---

## Phase 3: Core Scraper

### Task 7: URL Extractor

**Files:**
- Create: `scraper/extractor.py`
- Create: `tests/test_extractor.py`

- [ ] **Step 1: Write failing extractor tests**

```python
import pytest
from scraper.extractor import extract_media_urls, MEDIA_EXTENSIONS


def test_extract_image_links():
    html = """
    <html><body>
    <img src="photo.jpg">
    <img src="/images/logo.png">
    <a href="document.pdf">PDF</a>
    <script>var x = "other.txt"</script>
    </body></html>
    """
    urls = extract_media_urls(html, "http://example.com/page/")
    exts = [u.split(".")[-1] for u in urls]
    assert "jpg" in exts
    assert "png" in exts
    assert "pdf" in exts


def test_extract_video_links():
    html = '<source src="movie.mp4"><a href="clip.avi">clip</a>'
    urls = extract_media_urls(html, "http://example.com")
    assert any("mp4" in u for u in urls)
    assert any("avi" in u for u in urls)


def test_extract_absolute_urls():
    html = '<img src="/images/photo.jpg"><img src="https://cdn.example.com/img.png">'
    urls = extract_media_urls(html, "http://example.com")
    assert "http://example.com/images/photo.jpg" in urls
    assert "https://cdn.example.com/img.png" in urls


def test_filter_include():
    html = '<img src="a.jpg"><img src="b.png"><img src="c.gif">'
    urls = extract_media_urls(html, "http://example.com", include_filters=["*.jpg", "*.png"])
    assert len(urls) == 2


def test_filter_exclude():
    html = '<img src="a.jpg"><img src="b.png">'
    urls = extract_media_urls(html, "http://example.com", exclude_filters=["*.png"])
    assert len(urls) == 1
    assert "b.png" not in urls[0]


def test_skip_non_media():
    html = '<a href="/about.html">About</a><a href="/style.css">CSS</a>'
    urls = extract_media_urls(html, "http://example.com")
    assert len(urls) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/project-SIMC && python -m pytest tests/test_extractor.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Write extractor.py**

```python
import re
from urllib.parse import urljoin, urlparse
from fnmatch import fnmatch


MEDIA_EXTENSIONS = (
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif", ".heic",
    # Videos
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".ts", ".m3u8",
    # Audio
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".epub",
    # Archives
    ".zip", ".rar", ".7z", ".tar", ".gz",
)

URL_PATTERN = re.compile(
    r"""(?i)(?:src|href|data-src|data-url|content)\s*=\s*["']([^"']+\.(?:"""
    + "|".join(ext.strip(".") for ext in MEDIA_EXTENSIONS)
    + r"""))["']"""
)

M3U8_PATTERN = re.compile(r'["\']([^"\']+\.m3u8[^"\']*)["\']')


def extract_media_urls(html: str, base_url: str,
                       include_filters: list[str] = None,
                       exclude_filters: list[str] = None) -> list[str]:
    urls = set()
    for match in URL_PATTERN.finditer(html):
        url = match.group(1)
        full_url = urljoin(base_url, url)
        urls.add(full_url)
    for match in M3U8_PATTERN.finditer(html):
        urls.add(urljoin(base_url, match.group(1)))

    result = list(urls)

    if include_filters:
        result = [u for u in result if any(
            fnmatch(urlparse(u).path.lower(), f.lower()) for f in include_filters
        )]

    if exclude_filters:
        result = [u for u in result if not any(
            fnmatch(urlparse(u).path.lower(), f.lower()) for f in exclude_filters
        )]

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/project-SIMC && python -m pytest tests/test_extractor.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: URL extractor for media links from HTML with include/exclude filters"
```

---

### Task 8: Downloader with resume support

**Files:**
- Create: `scraper/downloader.py`
- Create: `tests/test_downloader.py`

- [ ] **Step 1: Write failing downloader tests**

```python
import pytest
from pathlib import Path
from scraper.downloader import Downloader


@pytest.mark.asyncio
async def test_download_creates_file(tmp_path):
    dl = Downloader(output_dir=str(tmp_path))
    content = b"Hello download test"
    result = await dl.download_file(
        url="http://example.com/test.txt",
        output_dir=str(tmp_path),
        filename="test.txt",
    )
    assert result["status"] == "completed"
    assert result["file_size"] == len(content)
    filepath = tmp_path / "test.txt"
    assert filepath.read_bytes() == content


@pytest.mark.asyncio
async def test_download_callback(tmp_path):
    dl = Downloader(output_dir=str(tmp_path))
    progress_data = []

    async def progress_cb(task_id, dl_id, downloaded, total):
        progress_data.append((downloaded, total))

    result = await dl.download_file(
        url="http://example.com/test.txt",
        output_dir=str(tmp_path),
        filename="test.txt",
        task_id=1,
        dl_id=1,
        progress_callback=progress_cb,
    )
    assert result["status"] == "completed"
    assert len(progress_data) > 0


@pytest.mark.asyncio
async def test_sanitize_filename():
    assert Downloader.sanitize_filename("hello/world:file.txt") == "hello_world_file.txt"
    assert Downloader.sanitize_filename("正常文件名.jpg") == "正常文件名.jpg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/project-SIMC && python -m pytest tests/test_downloader.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Write downloader.py**

```python
import re
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from urllib.parse import urlparse


class Downloader:
    CHUNK_SIZE = 64 * 1024

    def __init__(self, output_dir: str = "./downloads", max_retries: int = 3):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        name = re.sub(r'[<>:"/\\|?*]', "_", filename)
        return name.strip() or "unnamed"

    @staticmethod
    def extract_filename(url: str) -> str:
        path = urlparse(url).path
        name = Path(path).name or "unnamed"
        return Downloader.sanitize_filename(name)

    async def download_file(self, url: str, output_dir: str = None,
                            filename: str = None, task_id: int = None,
                            dl_id: int = None, progress_callback=None,
                            headers: dict = None, timeout: int = 30,
                            resume_from: int = 0) -> dict:
        out_dir = Path(output_dir) if output_dir else self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or self.extract_filename(url)
        filepath = out_dir / fname

        for attempt in range(self.max_retries):
            try:
                req_headers = headers.copy() if headers else {}
                if resume_from > 0:
                    req_headers["Range"] = f"bytes={resume_from}-"

                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=req_headers,
                                           timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                        if resp.status not in (200, 206):
                            if attempt < self.max_retries - 1:
                                await asyncio.sleep(2 ** attempt)
                                continue
                            return {"status": "failed", "error_msg": f"HTTP {resp.status}"}

                        total_size = resp.content_length
                        if total_size:
                            total_size += resume_from

                        mode = "ab" if resume_from > 0 else "wb"
                        async with aiofiles.open(filepath, mode) as f:
                            downloaded = resume_from
                            async for chunk in resp.content.iter_chunked(self.CHUNK_SIZE):
                                await f.write(chunk)
                                downloaded += len(chunk)
                                if progress_callback and task_id and dl_id:
                                    await progress_callback(task_id, dl_id, downloaded, total_size)

                        return {
                            "status": "completed",
                            "file_size": downloaded,
                            "filename": fname,
                            "filepath": str(filepath),
                        }
            except asyncio.TimeoutError:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"status": "failed", "error_msg": "Timeout"}
            except Exception as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"status": "failed", "error_msg": str(e)}

        return {"status": "failed", "error_msg": "Max retries exceeded"}
```

- [ ] **Step 4: Patch the test to mock aiohttp**

Actually tests will fail because they try real HTTP. We need a mock. Update `tests/test_downloader.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from scraper.downloader import Downloader


@pytest.mark.asyncio
async def test_download_creates_file(tmp_path):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.content_length = 18
    mock_resp.content = MagicMock()
    mock_resp.content.iter_chunked = MagicMock(return_value=iter([b"Hello download test"]))

    mock_session = MagicMock()
    mock_session.get = AsyncMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("scraper.downloader.aiohttp.ClientSession", return_value=mock_session):
        dl = Downloader(output_dir=str(tmp_path))
        result = await dl.download_file(
            url="http://example.com/test.txt",
            output_dir=str(tmp_path),
            filename="test.txt",
        )
        assert result["status"] == "completed"
        assert result["file_size"] == 18
        filepath = tmp_path / "test.txt"
        assert filepath.read_bytes() == b"Hello download test"


@pytest.mark.asyncio
async def test_download_callback(tmp_path):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.content_length = 100
    mock_resp.content = MagicMock()
    mock_resp.content.iter_chunked = MagicMock(return_value=iter([b"A" * 100]))

    mock_session = MagicMock()
    mock_session.get = AsyncMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

    progress = []
    async def cb(task_id, dl_id, down, total):
        progress.append((down, total))

    with patch("scraper.downloader.aiohttp.ClientSession", return_value=mock_session):
        dl = Downloader(output_dir=str(tmp_path))
        result = await dl.download_file(
            url="http://example.com/test.txt",
            output_dir=str(tmp_path),
            filename="test.txt",
            task_id=1, dl_id=1,
            progress_callback=cb,
        )
        assert result["status"] == "completed"
        assert len(progress) > 0
        assert progress[-1] == (100, 100)


def test_sanitize_filename():
    assert Downloader.sanitize_filename("hello/world:file.txt") == "hello_world_file.txt"


def test_extract_filename():
    assert Downloader.extract_filename("http://example.com/path/to/file.jpg") == "file.jpg"
    assert Downloader.extract_filename("http://example.com/") == "unnamed"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /root/project-SIMC && python -m pytest tests/test_downloader.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: async downloader with retry, resume via Range header, and progress callback"
```

---

### Task 9: Task Manager

**Files:**
- Create: `scraper/task_manager.py`

- [ ] **Step 1: Write task_manager.py**

```python
import asyncio
import json
from scraper.decryptors import register_all


class TaskManager:
    def __init__(self, max_global_concurrency: int = 20):
        self._semaphore = asyncio.Semaphore(max_global_concurrency)
        self._running_tasks: dict[int, asyncio.Task] = {}
        self._pause_events: dict[int, asyncio.Event] = {}
        self._progress_callbacks: list = []

    def register_progress_callback(self, cb):
        self._progress_callbacks.append(cb)

    def unregister_progress_callback(self, cb):
        if cb in self._progress_callbacks:
            self._progress_callbacks.remove(cb)

    async def broadcast_progress(self, task_id: int, done: int, total: int,
                                 current_file: str = "", speed: float = 0):
        for cb in self._progress_callbacks:
            try:
                await cb(task_id, done, total, current_file, speed)
            except Exception:
                pass

    async def start_task(self, task_id: int, task_config: dict):
        from db import queries as q
        from scraper.engine import ScraperEngine

        task = await q.get_task(task_id)
        if not task or task["status"] != "pending":
            return

        await q.update_task(task_id, status="running")
        config = json.loads(task["config"]) if task["config"] else {}
        config.update(task_config)

        register_all()

        self._pause_events[task_id] = asyncio.Event()
        self._pause_events[task_id].set()

        engine = ScraperEngine(
            task_id=task_id,
            semaphore=self._semaphore,
            pause_event=self._pause_events[task_id],
            progress_cb=self._broadcast_task_progress,
        )
        coro = engine.run()
        t = asyncio.create_task(coro)
        self._running_tasks[task_id] = t

    async def _broadcast_task_progress(self, task_id, done, total, current_file="", speed=0):
        await self.broadcast_progress(task_id, done, total, current_file, speed)
        from db import queries as q
        await q.update_task(task_id, done_files=done, total_files=total)

    async def pause_task(self, task_id: int):
        if task_id in self._pause_events:
            self._pause_events[task_id].clear()
        from db import queries as q
        await q.update_task(task_id, status="paused")

    async def resume_task(self, task_id: int):
        from db import queries as q
        task = await q.get_task(task_id)
        if not task or task["status"] != "paused":
            return
        if task_id not in self._running_tasks:
            await q.update_task(task_id, status="pending")
            await self.start_task(task_id, json.loads(task["config"]))
        else:
            self._pause_events[task_id].set()
            await q.update_task(task_id, status="running")

    async def retry_task(self, task_id: int):
        from db import queries as q
        failed = await q.get_failed_downloads(task_id)
        for dl in failed:
            await q.update_download(dl["id"], status="pending", retry_count=0, error_msg=None)
        await q.update_task(task_id, status="pending")
        task = await q.get_task(task_id)
        if task:
            config = json.loads(task["config"]) if task["config"] else {}
            await self.start_task(task_id, config)

    async def shutdown(self):
        for task_id in list(self._running_tasks.keys()):
            await self.pause_task(task_id)
        for t in self._running_tasks.values():
            t.cancel()
        for t in self._running_tasks.values():
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._running_tasks.clear()
        self._pause_events.clear()
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: task manager with concurrency control, pause/resume, and progress broadcasting"
```

---

### Task 10: Scraper Engine (orchestrator)

**Files:**
- Create: `scraper/engine.py`

- [ ] **Step 1: Write engine.py**

```python
import asyncio
import json
import time
import aiohttp
from pathlib import Path
from scraper.extractor import extract_media_urls
from scraper.decryptors import register_all, run_pipeline
from scraper.downloader import Downloader


class ScraperEngine:
    def __init__(self, task_id: int, semaphore: asyncio.Semaphore,
                 pause_event: asyncio.Event, progress_cb=None):
        self.task_id = task_id
        self._semaphore = semaphore
        self._pause_event = pause_event
        self._progress_cb = progress_cb
        self._downloader = Downloader()

    async def run(self):
        from db import queries as q

        register_all()
        task = await q.get_task(self.task_id)
        if not task:
            return
        config = json.loads(task["config"]) if task["config"] else {}
        concurrency = config.get("concurrency", 5)
        request_delay = config.get("request_delay_sec", 0.5)
        timeout = config.get("request_timeout_sec", 30)
        max_retries = config.get("max_retries", 3)
        output_dir = config.get("output_dir", "./downloads")
        decryptors_enabled = config.get("decryptors", [])
        decryptor_opts = config.get("decryptor_opts", {})
        include_filters = config.get("url_filters", {}).get("include")
        exclude_filters = config.get("url_filters", {}).get("exclude")
        headers = config.get("custom_headers", {})

        page_html = await self._fetch_page(task["url"], headers, timeout)
        if page_html is None:
            await q.update_task(self.task_id, status="failed", error_msg="Failed to fetch page")
            return

        urls = extract_media_urls(page_html, task["url"], include_filters, exclude_filters)
        if not urls:
            await q.update_task(self.task_id, status="completed", total_files=0, done_files=0)
            return

        for url in urls:
            filename = Downloader.extract_filename(url)
            await q.create_download(self.task_id, url, filename)

        total = len(urls)
        await q.update_task(self.task_id, total_files=total)

        sem = asyncio.Semaphore(concurrency)
        done_count = 0
        start_time = time.time()

        downloads = await q.list_downloads(self.task_id)

        async def download_one(dl):
            nonlocal done_count
            async with sem:
                await self._pause_event.wait()
                await q.update_download(dl["id"], status="downloading")
                dl_config = {"max_retries": max_retries, "file_size": dl.get("file_size", 0), **dl}

                dl_result = await self._downloader.download_file(
                    url=dl["url"],
                    output_dir=output_dir,
                    filename=dl["filename"],
                    task_id=self.task_id,
                    dl_id=dl["id"],
                    progress_callback=self._on_progress,
                    headers=headers,
                    timeout=timeout,
                )

                if dl_result["status"] == "completed":
                    await q.update_download(dl["id"], status="completed",
                                            file_size=dl_result["file_size"])
                else:
                    retry_count = dl.get("retry_count", 0) + 1
                    if retry_count < max_retries:
                        await q.update_download(dl["id"], status="pending",
                                                retry_count=retry_count,
                                                error_msg=dl_result.get("error_msg"))
                        await asyncio.sleep(2 ** retry_count)
                        await download_one(dl)
                    else:
                        await q.update_download(dl["id"], status="failed",
                                                error_msg=dl_result.get("error_msg"))

                done_count += 1
                elapsed = time.time() - start_time
                speed = done_count / elapsed if elapsed > 0 else 0
                if self._progress_cb:
                    await self._progress_cb(self.task_id, done_count, total, dl["filename"], speed)

        tasks = [download_one(dl) for dl in downloads]
        await asyncio.gather(*tasks, return_exceptions=True)

        await self._pause_event.wait()
        failed_count = await q.count_downloads_by_status(self.task_id, "failed")
        if failed_count == total:
            await q.update_task(self.task_id, status="failed", error_msg="All downloads failed")
        else:
            await q.update_task(self.task_id, status="completed", done_files=done_count)

    async def _on_progress(self, task_id, dl_id, downloaded, total):
        from db import queries as q
        await q.update_download(dl_id, downloaded=downloaded, file_size=total)

    async def _fetch_page(self, url: str, headers: dict, timeout: int) -> str | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status == 200:
                        return await resp.text()
        except Exception:
            pass
        return None
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: scraper engine orchestrating extract → download pipeline with concurrency"
```

---

## Phase 4: API Layer

### Task 11: Tasks API endpoints

**Files:**
- Create: `api/tasks.py`

- [ ] **Step 1: Write api/tasks.py**

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import queries as q

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreateBody(BaseModel):
    name: str
    url: str
    config: dict = {}


class TaskUpdateBody(BaseModel):
    name: str = None
    url: str = None
    config: dict = None


@router.get("")
async def list_tasks(status: str = None, offset: int = 0, limit: int = 20):
    tasks = await q.list_tasks(status=status, offset=offset, limit=limit)
    return {"tasks": tasks}


@router.post("")
async def create_task(body: TaskCreateBody):
    task = await q.create_task(body.name, body.url, body.config)
    return {"task": task}


@router.get("/{task_id}")
async def get_task(task_id: int):
    task = await q.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"task": task}


@router.put("/{task_id}")
async def update_task(task_id: int, body: TaskUpdateBody):
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    task = await q.update_task(task_id, **kwargs)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"task": task}


@router.delete("/{task_id}")
async def delete_task(task_id: int):
    deleted = await q.delete_task(task_id)
    if not deleted:
        raise HTTPException(404, "Task not found")
    return {"ok": True}


@router.post("/{task_id}/start")
async def start_task(task_id: int):
    from app import task_manager
    task = await q.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    import json
    config = json.loads(task["config"]) if task["config"] else {}
    await task_manager.start_task(task_id, config)
    return {"ok": True}


@router.post("/{task_id}/pause")
async def pause_task(task_id: int):
    from app import task_manager
    await task_manager.pause_task(task_id)
    return {"ok": True}


@router.post("/{task_id}/resume")
async def resume_task(task_id: int):
    from app import task_manager
    await task_manager.resume_task(task_id)
    return {"ok": True}


@router.post("/{task_id}/retry")
async def retry_task(task_id: int):
    from app import task_manager
    await task_manager.retry_task(task_id)
    return {"ok": True}
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: task CRUD and control API endpoints"
```

---

### Task 12: Downloads API endpoints

**Files:**
- Create: `api/downloads.py`

- [ ] **Step 1: Write api/downloads.py**

```python
from fastapi import APIRouter
from db import queries as q

router = APIRouter(prefix="/api/tasks/{task_id}/downloads", tags=["downloads"])


@router.get("")
async def list_downloads(task_id: int, status: str = None):
    downloads = await q.list_downloads(task_id, status=status)
    return {"downloads": downloads}
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: downloads list API endpoint"
```

---

### Task 13: Settings API endpoints

**Files:**
- Create: `api/settings.py`

- [ ] **Step 1: Write api/settings.py**

```python
from fastapi import APIRouter
from pydantic import BaseModel
from db import queries as q

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings():
    settings = await q.get_settings()
    return {"settings": settings}


@router.put("")
async def update_settings(body: dict):
    for key, value in body.items():
        await q.update_setting(key, str(value) if not isinstance(value, str) else value)
    settings = await q.get_settings()
    return {"settings": settings}
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: settings get/update API endpoints"
```

---

### Task 14: Files API endpoints

**Files:**
- Create: `api/files.py`

- [ ] **Step 1: Write api/files.py**

```python
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("")
async def list_files(dir: str = "./downloads"):
    base = Path(dir).resolve()
    if not base.exists():
        return {"files": []}
    files = []
    for f in sorted(base.rglob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.name != ".gitkeep":
            stat = f.stat()
            files.append({
                "name": f.name,
                "path": str(f.relative_to(base)),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
    return {"files": files[:200]}


@router.get("/download/{filename:path}")
async def download_file(filename: str, dir: str = "./downloads"):
    base = Path(dir).resolve()
    filepath = base / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(filepath, filename=filepath.name)
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: file browsing and download serving API endpoints"
```

---

### Task 15: WebSocket handler

**Files:**
- Create: `api/websocket.py`

- [ ] **Step 1: Write api/websocket.py**

```python
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

active_connections: list[WebSocket] = []


@router.websocket("/ws/progress")
async def websocket_progress(ws: WebSocket):
    await ws.accept()
    active_connections.append(ws)

    async def progress_callback(task_id, done, total, current_file="", speed=0):
        try:
            await ws.send_json({
                "type": "progress",
                "task_id": task_id,
                "done": done,
                "total": total,
                "current_file": current_file,
                "speed": round(speed, 2),
            })
        except Exception:
            pass

    from app import task_manager
    task_manager.register_progress_callback(progress_callback)

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        task_manager.unregister_progress_callback(progress_callback)
        if ws in active_connections:
            active_connections.remove(ws)
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: WebSocket progress handler for real-time download updates"
```

---

## Phase 5: Frontend (Web UI)

> **IMPORTANT:** Before starting each frontend task, invoke the `frontend-design:frontend-design` skill for guidance on producing distinctive, high-quality frontend code.

### Task 16: HTML shell, CSS, and JS skeleton

**Files:**
- Create: `webui/index.html`
- Create: `webui/css/style.css`
- Create: `webui/js/app.js`
- Create: `webui/js/api.js`

- [ ] **Step 1: Write webui/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Web Scraper</title>
    <link rel="stylesheet" href="/webui/css/style.css">
</head>
<body>
    <nav class="sidebar">
        <div class="sidebar-brand">
            <h1>Scraper</h1>
        </div>
        <ul class="nav-links">
            <li><a href="#dashboard" class="nav-link active" data-page="dashboard">Dashboard</a></li>
            <li><a href="#new-task" class="nav-link" data-page="new-task">New Task</a></li>
            <li><a href="#downloads" class="nav-link" data-page="downloads">Downloads</a></li>
            <li><a href="#settings" class="nav-link" data-page="settings">Settings</a></li>
            <li><a href="#files" class="nav-link" data-page="files">Files</a></li>
        </ul>
        <div class="sidebar-footer">
            <span id="ws-status" class="ws-status disconnected">Disconnected</span>
        </div>
    </nav>
    <main id="main-content" class="main-content"></main>

    <script src="/webui/js/api.js"></script>
    <script src="/webui/js/app.js"></script>
    <script src="/webui/js/dashboard.js"></script>
    <script src="/webui/js/task-form.js"></script>
    <script src="/webui/js/downloads.js"></script>
    <script src="/webui/js/settings.js"></script>
    <script src="/webui/js/files.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write webui/css/style.css**

```css
:root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2a2d3a;
    --text: #e1e4ed;
    --text-muted: #8b8fa3;
    --accent: #6c8cff;
    --accent-hover: #8ba3ff;
    --success: #3ecf8e;
    --warning: #f0c040;
    --danger: #f06060;
    --radius: 8px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    display: flex;
    min-height: 100vh;
}

.sidebar {
    width: 220px;
    background: var(--surface);
    border-right: 1px solid var(--border);
    padding: 20px 0;
    display: flex;
    flex-direction: column;
    position: fixed;
    top: 0; left: 0; bottom: 0;
}

.sidebar-brand {
    padding: 0 20px 20px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 12px;
}

.sidebar-brand h1 { font-size: 18px; font-weight: 700; color: var(--accent); }

.nav-links { list-style: none; flex: 1; }

.nav-link {
    display: block;
    padding: 10px 20px;
    color: var(--text-muted);
    text-decoration: none;
    font-size: 14px;
    transition: all 0.15s;
    border-left: 3px solid transparent;
}

.nav-link:hover { color: var(--text); background: rgba(255,255,255,0.03); }
.nav-link.active { color: var(--accent); background: rgba(108,140,255,0.08); border-left-color: var(--accent); }

.sidebar-footer { padding: 12px 20px; border-top: 1px solid var(--border); }

.ws-status { font-size: 11px; }
.ws-status.connected { color: var(--success); }
.ws-status.disconnected { color: var(--danger); }

.main-content {
    margin-left: 220px;
    flex: 1;
    padding: 32px;
    max-width: 1200px;
}

.page { display: none; }
.page.active { display: block; }

/* Cards */
.card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    margin-bottom: 16px;
}

.stat-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }

.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; text-align: center; }
.stat-card .stat-value { font-size: 32px; font-weight: 700; }
.stat-card .stat-label { font-size: 12px; color: var(--text-muted); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
.stat-value.running { color: var(--accent); }
.stat-value.completed { color: var(--success); }
.stat-value.failed { color: var(--danger); }

/* Forms */
.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 13px; color: var(--text-muted); margin-bottom: 6px; font-weight: 500; }

input, select, textarea {
    width: 100%;
    padding: 10px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 14px;
    font-family: inherit;
    transition: border-color 0.15s;
}

input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); }

.btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 8px 16px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s;
    text-decoration: none;
}

.btn:hover { background: var(--border); }
.btn-primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn-primary:hover { background: var(--accent-hover); }
.btn-danger { border-color: var(--danger); color: var(--danger); }
.btn-danger:hover { background: var(--danger); color: #fff; }
.btn-sm { padding: 4px 10px; font-size: 12px; }
.btn-group { display: flex; gap: 8px; }

/* Tables */
table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 12px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); }
th { color: var(--text-muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
tr:hover td { background: rgba(255,255,255,0.02); }

/* Badges */
.badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 11px; font-weight: 600; text-transform: uppercase;
}
.badge-pending { background: rgba(240,192,64,0.15); color: var(--warning); }
.badge-running { background: rgba(108,140,255,0.15); color: var(--accent); }
.badge-completed { background: rgba(62,207,142,0.15); color: var(--success); }
.badge-failed { background: rgba(240,96,96,0.15); color: var(--danger); }
.badge-paused { background: rgba(139,143,163,0.15); color: var(--text-muted); }

/* Progress bar */
.progress-bar {
    height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; margin: 4px 0;
}
.progress-fill { height: 100%; background: var(--accent); transition: width 0.3s; border-radius: 3px; }

/* Checkbox group */
.checkbox-group { display: flex; flex-wrap: wrap; gap: 8px; }
.checkbox-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: var(--bg); border: 1px solid var(--border); border-radius: 16px; font-size: 12px; cursor: pointer; user-select: none; }
.checkbox-chip input { display: none; }
.checkbox-chip.checked { background: rgba(108,140,255,0.15); border-color: var(--accent); color: var(--accent); }

/* Toast */
.toast { position: fixed; bottom: 24px; right: 24px; padding: 12px 20px; border-radius: 8px; font-size: 13px; z-index: 999; animation: slideIn 0.3s; }
.toast-success { background: var(--success); color: #000; }
.toast-error { background: var(--danger); color: #fff; }

@keyframes slideIn { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

/* Key-value editor */
.kv-editor { display: flex; flex-direction: column; gap: 8px; }
.kv-row { display: flex; gap: 8px; }
.kv-row input { flex: 1; }

/* Section heading */
.section-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--text); }
```

- [ ] **Step 3: Write webui/js/api.js**

```javascript
const API = {
    _base: '/api',

    async get(path) {
        const r = await fetch(this._base + path);
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    },

    async post(path, body = {}) {
        const r = await fetch(this._base + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    },

    async put(path, body = {}) {
        const r = await fetch(this._base + path, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    },

    async del(path) {
        const r = await fetch(this._base + path, { method: 'DELETE' });
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    },

    // Tasks
    tasks: {
        list: (status, offset = 0) => API.get(`/tasks?status=${status || ''}&offset=${offset}`),
        get: (id) => API.get(`/tasks/${id}`),
        create: (name, url, config) => API.post('/tasks', { name, url, config }),
        update: (id, data) => API.put(`/tasks/${id}`, data),
        delete: (id) => API.del(`/tasks/${id}`),
        start: (id) => API.post(`/tasks/${id}/start`),
        pause: (id) => API.post(`/tasks/${id}/pause`),
        resume: (id) => API.post(`/tasks/${id}/resume`),
        retry: (id) => API.post(`/tasks/${id}/retry`),
        downloads: (id, status) => API.get(`/tasks/${id}/downloads?status=${status || ''}`),
    },

    settings: {
        get: () => API.get('/settings'),
        update: (data) => API.put('/settings', data),
    },

    files: {
        list: (dir) => API.get(`/files?dir=${encodeURIComponent(dir || './downloads')}`),
        downloadUrl: (filename, dir) => `/api/files/download/${encodeURIComponent(filename)}?dir=${encodeURIComponent(dir || './downloads')}`,
    },
};
```

- [ ] **Step 4: Write webui/js/app.js**

```javascript
const WS = {
    _ws: null,
    _callbacks: [],

    connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this._ws = new WebSocket(`${proto}//${location.host}/ws/progress`);

        this._ws.onopen = () => {
            document.getElementById('ws-status').textContent = 'Connected';
            document.getElementById('ws-status').className = 'ws-status connected';
        };

        this._ws.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            if (msg.type === 'progress') {
                this._callbacks.forEach(cb => cb(msg));
            }
        };

        this._ws.onclose = () => {
            document.getElementById('ws-status').textContent = 'Disconnected';
            document.getElementById('ws-status').className = 'ws-status disconnected';
            setTimeout(() => this.connect(), 3000);
        };

        this._ws.onerror = () => {};
    },

    onProgress(cb) { this._callbacks.push(cb); return () => { this._callbacks = this._callbacks.filter(c => c !== cb); }; },
};

const Router = {
    _current: null,

    navigate(page) {
        if (this._current === page) return;
        this._current = page;

        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        const link = document.querySelector(`[data-page="${page}"]`);
        if (link) link.classList.add('active');

        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        const el = document.getElementById(`page-${page}`);
        if (el) el.classList.add('active');

        if (page === 'dashboard') Dashboard.render();
        else if (page === 'new-task') TaskForm.render();
        else if (page === 'downloads') Downloads.render();
        else if (page === 'settings') Settings.render();
        else if (page === 'files') Files.render();
    },
};

function toast(msg, type = 'success') {
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

function formatSize(bytes) {
    if (!bytes) return '-';
    const u = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (bytes >= 1024 && i < u.length - 1) { bytes /= 1024; i++; }
    return `${bytes.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function statusBadge(status) {
    return `<span class="badge badge-${status}">${status}</span>`;
}

document.addEventListener('DOMContentLoaded', () => {
    WS.connect();
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            Router.navigate(link.dataset.page);
        });
    });
    Router.navigate('dashboard');
});
```

- [ ] **Step 5: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: frontend shell with sidebar nav, CSS design system, API client, WebSocket, and SPA router"
```

---

### Task 17: Dashboard page

**Files:**
- Create: `webui/js/dashboard.js`

- [ ] **Step 1: Write webui/js/dashboard.js**

```javascript
const Dashboard = {
    async render() {
        const main = document.getElementById('main-content');
        main.innerHTML = `
            <div class="page active" id="page-dashboard">
                <h2 style="font-size:20px;margin-bottom:20px;">Dashboard</h2>
                <div class="stat-cards" id="stat-cards"></div>
                <div id="active-tasks-section"></div>
                <div class="card"><h3 class="section-title">Recent Tasks</h3>
                    <table><thead><tr><th>Name</th><th>URL</th><th>Status</th><th>Progress</th><th>Created</th><th></th></tr></thead>
                    <tbody id="recent-tasks"></tbody></table>
                </div>
            </div>`;

        await this.loadStats();
        this.listenProgress();
    },

    async loadStats() {
        try {
            const data = await API.tasks.list('', 0);
            const tasks = data.tasks || [];
            const running = tasks.filter(t => t.status === 'running').length;
            const completed = tasks.filter(t => t.status === 'completed').length;
            const failed = tasks.filter(t => t.status === 'failed').length;

            document.getElementById('stat-cards').innerHTML = `
                <div class="stat-card"><div class="stat-value running">${running}</div><div class="stat-label">Running</div></div>
                <div class="stat-card"><div class="stat-value completed">${completed}</div><div class="stat-label">Completed</div></div>
                <div class="stat-card"><div class="stat-value failed">${failed}</div><div class="stat-label">Failed</div></div>
                <div class="stat-card"><div class="stat-value">${tasks.length}</div><div class="stat-label">Total</div></div>`;

            document.getElementById('recent-tasks').innerHTML = tasks.slice(0, 20).map(t => `
                <tr>
                    <td><strong>${escHtml(t.name)}</strong></td>
                    <td style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtml(t.url)}</td>
                    <td>${statusBadge(t.status)}</td>
                    <td>
                        <div class="progress-bar"><div class="progress-fill" style="width:${t.total_files ? (t.done_files / t.total_files * 100) : 0}%"></div></div>
                        <small>${t.done_files || 0}/${t.total_files || 0}</small>
                    </td>
                    <td style="color:var(--text-muted);font-size:12px;">${t.created_at || ''}</td>
                    <td>
                        ${t.status === 'running' ? `<button class="btn btn-sm" onclick="Dashboard.pauseTask(${t.id})">Pause</button>` : ''}
                        ${t.status === 'paused' ? `<button class="btn btn-sm btn-primary" onclick="Dashboard.resumeTask(${t.id})">Resume</button>` : ''}
                        ${t.status === 'failed' ? `<button class="btn btn-sm btn-primary" onclick="Dashboard.retryTask(${t.id})">Retry</button>` : ''}
                    </td>
                </tr>`).join('') || '<tr><td colspan="6" style="color:var(--text-muted);text-align:center;">No tasks yet</td></tr>';
        } catch (e) {
            console.error('Dashboard load error:', e);
        }
    },

    listenProgress() {
        WS.onProgress((msg) => {
            this.loadStats();
        });
    },

    async pauseTask(id) { await API.tasks.pause(id); toast('Task paused'); this.loadStats(); },
    async resumeTask(id) { await API.tasks.resume(id); toast('Task resumed'); this.loadStats(); },
    async retryTask(id) { await API.tasks.retry(id); toast('Retrying...'); this.loadStats(); },
};

function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: dashboard page with stats cards, task list, and live progress"
```

---

### Task 18: Task Form page

**Files:**
- Create: `webui/js/task-form.js`

- [ ] **Step 1: Write webui/js/task-form.js**

```javascript
const MEDIA_PRESETS = {
    images: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif', 'heic'],
    videos: ['mp4', 'mkv', 'webm', 'avi', 'mov', 'flv', 'wmv', 'ts', 'm3u8'],
    audio: ['mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a', 'opus'],
    documents: ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'epub'],
    archives: ['zip', 'rar', '7z', 'tar', 'gz'],
};

const DECRYPTORS = [
    { name: 'base64', label: 'Base64', hasConfig: false },
    { name: 'hex', label: 'Hex', hasConfig: false },
    { name: 'aes', label: 'AES', hasConfig: true },
    { name: 'xor', label: 'XOR', hasConfig: true },
    { name: 'url_sign', label: 'URL Sign Strip', hasConfig: false },
    { name: 'rot47', label: 'ROT47', hasConfig: false },
    { name: 'custom', label: 'Custom Expr', hasConfig: true },
];

const TaskForm = {
    render() {
        const main = document.getElementById('main-content');
        main.innerHTML = `
            <div class="page active" id="page-new-task">
                <h2 style="font-size:20px;margin-bottom:20px;">New Scraping Task</h2>
                <div class="card">
                    <div class="form-group"><label>Task Name</label><input id="task-name" placeholder="My scrape task"></div>
                    <div class="form-group"><label>Target URL</label><input id="task-url" placeholder="https://example.com/page/"></div>
                </div>
                <div class="card">
                    <h3 class="section-title">File Type Filters</h3>
                    ${Object.entries(MEDIA_PRESETS).map(([cat, exts]) => `
                        <div style="margin-bottom:12px;">
                            <strong style="font-size:12px;color:var(--text-muted);text-transform:uppercase;display:block;margin-bottom:6px;">${cat}</strong>
                            <div class="checkbox-group">${exts.map(ext => `
                                <label class="checkbox-chip checked" id="chip-${ext}">
                                    <input type="checkbox" checked data-ext="${ext}" onchange="TaskForm.toggleChip(this)">
                                    .${ext}
                                </label>`).join('')}</div>
                        </div>`).join('')}
                    <div class="form-group" style="margin-top:12px;">
                        <label>Custom Extensions (comma-separated)</label>
                        <input id="custom-exts" placeholder="dat, bin, tmp">
                    </div>
                </div>
                <div class="card">
                    <h3 class="section-title">Decryptors</h3>
                    ${DECRYPTORS.map(d => `
                        <div style="margin-bottom:12px;">
                            <label class="checkbox-chip" id="dec-chip-${d.name}">
                                <input type="checkbox" data-dec="${d.name}" onchange="TaskForm.toggleDec(this)">
                                ${d.label}
                            </label>
                            ${d.hasConfig ? `<div id="dec-config-${d.name}" style="display:none;margin-top:8px;">${TaskForm.decConfigHTML(d.name)}</div>` : ''}
                        </div>`).join('')}
                </div>
                <div class="card">
                    <h3 class="section-title">Advanced Options</h3>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                        <div class="form-group"><label>Concurrency</label><input id="opt-concurrency" type="number" value="5" min="1" max="20"></div>
                        <div class="form-group"><label>Request Delay (s)</label><input id="opt-delay" type="number" value="0.5" step="0.1" min="0"></div>
                        <div class="form-group"><label>Timeout (s)</label><input id="opt-timeout" type="number" value="30"></div>
                        <div class="form-group"><label>Max Retries</label><input id="opt-retries" type="number" value="3" min="0"></div>
                        <div class="form-group"><label>Max File Size (MB)</label><input id="opt-max-size" type="number" value="500"></div>
                        <div class="form-group"><label>Output Directory</label><input id="opt-output-dir" value="./downloads"></div>
                    </div>
                </div>
                <div class="card">
                    <h3 class="section-title">Custom Headers</h3>
                    <div class="kv-editor" id="headers-editor">
                        <div class="kv-row"><input placeholder="Header name" onchange="TaskForm.ensureHeaderRow()"><input placeholder="Value"></div>
                    </div>
                </div>
                <div style="margin-top:16px;">
                    <button class="btn btn-primary" onclick="TaskForm.submit()" style="padding:12px 32px;font-size:15px;">Start Scraping</button>
                </div>
            </div>`;
    },

    decConfigHTML(name) {
        if (name === 'aes') return `<div class="form-group"><label>AES Key (hex)</label><input id="dec-aes-key" placeholder="0123..."></div><div class="form-group"><label>IV (hex)</label><input id="dec-aes-iv" placeholder="0123..."></div><div class="form-group"><label>Mode</label><select id="dec-aes-mode"><option>CBC</option><option>ECB</option><option>GCM</option></select></div>`;
        if (name === 'xor') return `<div class="form-group"><label>XOR Key (hex)</label><input id="dec-xor-key" placeholder="55 or 0102..."></div>`;
        if (name === 'custom') return `<div class="form-group"><label>Python Expression</label><input id="dec-custom-expr" placeholder="bytes(b ^ 0xFF for b in content)"><small style="color:var(--text-muted);">Use <code>content</code> as the bytes variable</small></div>`;
        return '';
    },

    toggleChip(cb) { cb.parentElement.classList.toggle('checked', cb.checked); },
    toggleDec(cb) {
        cb.parentElement.classList.toggle('checked', cb.checked);
        const configDiv = document.getElementById(`dec-config-${cb.dataset.dec}`);
        if (configDiv) configDiv.style.display = cb.checked ? 'block' : 'none';
    },
    ensureHeaderRow() {
        const editor = document.getElementById('headers-editor');
        const rows = editor.querySelectorAll('.kv-row');
        const last = rows[rows.length - 1];
        if (last.querySelector('input').value || last.querySelectorAll('input')[1].value) {
            const row = document.createElement('div');
            row.className = 'kv-row';
            row.innerHTML = '<input placeholder="Header name" onchange="TaskForm.ensureHeaderRow()"><input placeholder="Value">';
            editor.appendChild(row);
        }
    },

    async submit() {
        const name = document.getElementById('task-name').value || 'Unnamed';
        const url = document.getElementById('task-url').value;
        if (!url) { toast('Please enter a URL', 'error'); return; }

        const include = [...document.querySelectorAll('[data-ext]:checked')].map(cb => `*.${cb.dataset.ext}`);
        const customExts = document.getElementById('custom-exts').value.split(',').map(s => s.trim()).filter(Boolean);
        customExts.forEach(e => include.push(`*.${e}`));

        const enabledDecs = [...document.querySelectorAll('[data-dec]:checked')].map(cb => cb.dataset.dec);
        const decOpts = {};
        if (enabledDecs.includes('aes')) {
            decOpts.aes = {
                key: document.getElementById('dec-aes-key')?.value || '',
                iv: document.getElementById('dec-aes-iv')?.value || '',
                mode: document.getElementById('dec-aes-mode')?.value || 'CBC',
            };
        }
        if (enabledDecs.includes('xor')) {
            decOpts.xor_key = document.getElementById('dec-xor-key')?.value || '';
        }
        if (enabledDecs.includes('custom')) {
            decOpts.custom_expr = document.getElementById('dec-custom-expr')?.value || '';
        }

        const headers = {};
        const rows = document.querySelectorAll('#headers-editor .kv-row');
        rows.forEach(row => {
            const inputs = row.querySelectorAll('input');
            if (inputs[0].value && inputs[1].value) headers[inputs[0].value] = inputs[1].value;
        });

        const config = {
            concurrency: parseInt(document.getElementById('opt-concurrency').value) || 5,
            output_dir: document.getElementById('opt-output-dir').value || './downloads',
            decryptors: enabledDecs,
            decryptor_opts: decOpts,
            url_filters: { include },
            custom_headers: headers,
            request_delay_sec: parseFloat(document.getElementById('opt-delay').value) || 0.5,
            request_timeout_sec: parseInt(document.getElementById('opt-timeout').value) || 30,
            max_retries: parseInt(document.getElementById('opt-retries').value) || 3,
            max_file_size_mb: parseInt(document.getElementById('opt-max-size').value) || 500,
        };

        try {
            const result = await API.tasks.create(name, url, config);
            await API.tasks.start(result.task.id);
            toast('Task started!');
            Router.navigate('dashboard');
        } catch (e) {
            toast('Error: ' + e.message, 'error');
        }
    },
};
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: task creation form with file type presets, decryptor config, and advanced options"
```

---

### Task 19: Downloads page

**Files:**
- Create: `webui/js/downloads.js`

- [ ] **Step 1: Write webui/js/downloads.js**

```javascript
const Downloads = {
    _currentTaskId: null,

    async render() {
        const main = document.getElementById('main-content');
        main.innerHTML = `
            <div class="page active" id="page-downloads">
                <h2 style="font-size:20px;margin-bottom:20px;">Downloads</h2>
                <div class="card">
                    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
                        <div class="form-group" style="margin:0;min-width:200px;">
                            <select id="dl-task-filter" onchange="Downloads.loadTable()">
                                <option value="">All Tasks</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin:0;flex:1;min-width:200px;">
                            <input id="dl-search" placeholder="Search filename..." oninput="Downloads.loadTable()">
                        </div>
                    </div>
                </div>
                <div class="card">
                    <table><thead><tr><th>Filename</th><th>Size</th><th>Status</th><th>Progress</th><th>Time</th><th></th></tr></thead>
                    <tbody id="dl-table-body"></tbody></table>
                    <div id="dl-empty" style="text-align:center;padding:40px;color:var(--text-muted);display:none;">No downloads yet</div>
                </div>
            </div>`;

        await this.loadTasks();
        await this.loadTable();
    },

    async loadTasks() {
        try {
            const data = await API.tasks.list();
            const sel = document.getElementById('dl-task-filter');
            sel.innerHTML = '<option value="">All Tasks</option>' +
                data.tasks.map(t => `<option value="${t.id}">#${t.id} - ${escHtml(t.name)}</option>`).join('');
            if (this._currentTaskId) sel.value = this._currentTaskId;
        } catch (e) { console.error(e); }
    },

    async loadTable() {
        const taskId = document.getElementById('dl-task-filter').value;
        this._currentTaskId = taskId;
        const search = (document.getElementById('dl-search').value || '').toLowerCase();
        let downloads = [];

        try {
            if (taskId) {
                const d = await API.tasks.downloads(parseInt(taskId));
                downloads = d.downloads || [];
            } else {
                const data = await API.tasks.list();
                for (const t of (data.tasks || [])) {
                    const d = await API.tasks.downloads(t.id);
                    downloads.push(...(d.downloads || []).map(dl => ({ ...dl, task_name: t.name })));
                }
            }

            if (search) {
                downloads = downloads.filter(d => (d.filename || '').toLowerCase().includes(search));
            }

            const tbody = document.getElementById('dl-table-body');
            const empty = document.getElementById('dl-empty');

            if (downloads.length === 0) {
                tbody.innerHTML = '';
                empty.style.display = 'block';
            } else {
                empty.style.display = 'none';
                tbody.innerHTML = downloads.map(d => `
                    <tr>
                        <td>${escHtml(d.filename || d.url)}</td>
                        <td>${formatSize(d.file_size)}</td>
                        <td>${statusBadge(d.status)}</td>
                        <td>
                            <div class="progress-bar"><div class="progress-fill" style="width:${d.file_size ? (d.downloaded / d.file_size * 100) : 0}%"></div></div>
                            <small>${d.status === 'completed' ? 'Done' : formatSize(d.downloaded) + (d.file_size ? ' / ' + formatSize(d.file_size) : '')}</small>
                        </td>
                        <td style="font-size:12px;color:var(--text-muted);">${d.created_at || ''}</td>
                        <td>
                            ${d.status === 'completed' ? `<a href="${API.files.downloadUrl(d.filename)}" class="btn btn-sm btn-primary">Download</a>` : ''}
                            ${d.status === 'failed' ? `<button class="btn btn-sm btn-danger">${d.error_msg || 'Failed'}</button>` : ''}
                        </td>
                    </tr>`).join('');
            }
        } catch (e) {
            console.error(e);
            document.getElementById('dl-table-body').innerHTML = '<tr><td colspan="6" style="color:var(--danger);text-align:center;">Error loading downloads</td></tr>';
        }
    },
};
```

- [ ] **Step 2: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: downloads page with task filter, search, and progress table"
```

---

### Task 20: Settings page + Files browser

**Files:**
- Create: `webui/js/settings.js`
- Create: `webui/js/files.js`

- [ ] **Step 1: Write webui/js/settings.js**

```javascript
const Settings = {
    async render() {
        const main = document.getElementById('main-content');
        main.innerHTML = `
            <div class="page active" id="page-settings">
                <h2 style="font-size:20px;margin-bottom:20px;">Settings</h2>
                <div class="card">
                    <h3 class="section-title">Defaults</h3>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                        <div class="form-group"><label>Default Concurrency</label><input id="set-concurrency" type="number" value="5" min="1" max="20"></div>
                        <div class="form-group"><label>Default Output Directory</label><input id="set-output-dir" value="./downloads"></div>
                    </div>
                </div>
                <div class="card">
                    <h3 class="section-title">AES Key Management</h3>
                    <div class="form-group"><label>AES Key (hex, 32 bytes)</label><input id="set-aes-key" placeholder="0123456789abcdef0123456789abcdef"></div>
                    <div class="form-group"><label>IV (hex, 16 bytes)</label><input id="set-aes-iv" placeholder="0123456789abcdef"></div>
                </div>
                <button class="btn btn-primary" onclick="Settings.save()">Save Settings</button>
            </div>`;

        try {
            const data = await API.settings.get();
            const s = data.settings || {};
            document.getElementById('set-concurrency').value = s.default_concurrency || '5';
            document.getElementById('set-output-dir').value = s.default_output_dir || './downloads';
            document.getElementById('set-aes-key').value = s.aes_key || '';
            document.getElementById('set-aes-iv').value = s.aes_iv || '';
        } catch (e) { console.error(e); }
    },

    async save() {
        try {
            await API.settings.update({
                default_concurrency: document.getElementById('set-concurrency').value,
                default_output_dir: document.getElementById('set-output-dir').value,
                aes_key: document.getElementById('set-aes-key').value,
                aes_iv: document.getElementById('set-aes-iv').value,
            });
            toast('Settings saved');
        } catch (e) { toast('Error: ' + e.message, 'error'); }
    },
};
```

- [ ] **Step 2: Write webui/js/files.js**

```javascript
const Files = {
    async render() {
        const main = document.getElementById('main-content');
        main.innerHTML = `
            <div class="page active" id="page-files">
                <h2 style="font-size:20px;margin-bottom:20px;">Downloaded Files</h2>
                <div class="card">
                    <table><thead><tr><th>Filename</th><th>Size</th><th>Path</th><th></th></tr></thead>
                    <tbody id="files-table"></tbody></table>
                    <div id="files-empty" style="text-align:center;padding:40px;color:var(--text-muted);display:none;">No files downloaded yet</div>
                </div>
            </div>`;

        try {
            const data = await API.files.list('./downloads');
            const files = data.files || [];
            if (files.length === 0) {
                document.getElementById('files-empty').style.display = 'block';
            } else {
                document.getElementById('files-table').innerHTML = files.map(f => `
                    <tr>
                        <td>${escHtml(f.name)}</td>
                        <td>${formatSize(f.size)}</td>
                        <td style="font-size:12px;color:var(--text-muted);max-width:300px;overflow:hidden;text-overflow:ellipsis;">${escHtml(f.path)}</td>
                        <td><a href="${API.files.downloadUrl(f.path)}" class="btn btn-sm btn-primary">Download</a></td>
                    </tr>`).join('');
            }
        } catch (e) {
            console.error(e);
            toast('Error loading files', 'error');
        }
    },
};
```

- [ ] **Step 3: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: settings page with defaults and AES key management, plus files browser page"
```

---

## Phase 6: Integration

### Task 21: Wire everything in app.py and add integration tests

**Files:**
- Modify: `app.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Update app.py to mount all routers, static files, and task_manager**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

BASE_DIR = Path(__file__).parent

from scraper.task_manager import TaskManager

task_manager = TaskManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from db.schema import init_db
    from scraper.decryptors import register_all
    await init_db()
    register_all()
    yield
    await task_manager.shutdown()


app = FastAPI(title="Web Scraper", lifespan=lifespan)

from api.tasks import router as tasks_router
from api.downloads import router as downloads_router
from api.settings import router as settings_router
from api.files import router as files_router
from api.websocket import router as ws_router

app.include_router(tasks_router)
app.include_router(downloads_router)
app.include_router(settings_router)
app.include_router(files_router)
app.include_router(ws_router)

webui_path = BASE_DIR / "webui"
if webui_path.exists():
    app.mount("/webui", StaticFiles(directory=str(webui_path)), name="webui")


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/webui/index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 2: Write integration tests**

```python
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
```

- [ ] **Step 3: Install httpx and run integration tests**

Run:
```bash
cd /root/project-SIMC && pip install httpx
cd /root/project-SIMC && python -m pytest tests/test_api.py -v
```
Expected: 8 passed

- [ ] **Step 4: Run all tests**

Run:
```bash
cd /root/project-SIMC && python -m pytest tests/ -v
```
Expected: All tests pass (26 total)

- [ ] **Step 5: Commit**

```bash
cd /root/project-SIMC && git add -A && git commit -m "feat: wire app.py with routers, static files, task manager; add integration tests"
```

---

### Task 22: Final verification

- [ ] **Step 1: Start the server**

Run:
```bash
cd /root/project-SIMC && timeout 5 python -m uvicorn app:app --host 0.0.0.0 --port 8000 2>&1 || true
```
Expected: Server starts without errors, outputs "Uvicorn running on..."

- [ ] **Step 2: Run full test suite one final time**

Run:
```bash
cd /root/project-SIMC && python -m pytest tests/ -v --tb=short
```
Expected: All tests pass.

- [ ] **Step 3: Verify final project structure**

Run:
```bash
cd /root/project-SIMC && find . -type f -not -path './.git/*' -not -path './__pycache__/*' -not -name '*.pyc' -not -name 'scraper.db' | sort
```
Expected: All planned files exist.

- [ ] **Step 4: Commit final state**

```bash
cd /root/project-SIMC && git add -A && git commit -m "chore: final verification, all tests passing"
```
