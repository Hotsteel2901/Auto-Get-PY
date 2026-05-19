from db.schema import get_db
import json


# --- Tasks ---

async def create_task(name: str, url: str, config: dict = None) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO tasks (name, url, config) VALUES (?, ?, ?)",
            (name, url, json.dumps(config or {})),
        )
        await db.commit()
        task_id = cur.lastrowid
        row = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        result = await row.fetchone()
        return dict(result)
    finally:
        await db.close()


async def list_tasks(status: str = None, offset: int = 0, limit: int = 20) -> list[dict]:
    db = await get_db()
    try:
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
        return results
    finally:
        await db.close()


async def get_task(task_id: int) -> dict | None:
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        result = await row.fetchone()
        return dict(result) if result else None
    finally:
        await db.close()


async def update_task(task_id: int, **kwargs) -> dict | None:
    if not kwargs:
        return await get_task(task_id)
    db = await get_db()
    try:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [task_id]
        await db.execute(f"UPDATE tasks SET {sets}, updated_at = datetime('now') WHERE id = ?", vals)
        await db.commit()
        row = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        result = await row.fetchone()
        return dict(result) if result else None
    finally:
        await db.close()


async def delete_task(task_id: int) -> bool:
    db = await get_db()
    try:
        cur = await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()
        deleted = cur.rowcount > 0
        return deleted
    finally:
        await db.close()


# --- Downloads ---

async def create_download(task_id: int, url: str, filename: str = None) -> dict:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO downloads (task_id, url, filename) VALUES (?, ?, ?)",
            (task_id, url, filename),
        )
        await db.commit()
        dl_id = cur.lastrowid
        row = await db.execute("SELECT * FROM downloads WHERE id = ?", (dl_id,))
        result = await row.fetchone()
        return dict(result)
    finally:
        await db.close()


async def list_downloads(task_id: int, status: str = None) -> list[dict]:
    db = await get_db()
    try:
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
        return results
    finally:
        await db.close()


async def get_download(dl_id: int) -> dict | None:
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM downloads WHERE id = ?", (dl_id,))
        result = await row.fetchone()
        return dict(result) if result else None
    finally:
        await db.close()


async def update_download(dl_id: int, **kwargs) -> dict | None:
    if not kwargs:
        return await get_download(dl_id)
    db = await get_db()
    try:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [dl_id]
        await db.execute(f"UPDATE downloads SET {sets} WHERE id = ?", vals)
        await db.commit()
        row = await db.execute("SELECT * FROM downloads WHERE id = ?", (dl_id,))
        result = await row.fetchone()
        return dict(result) if result else None
    finally:
        await db.close()


async def count_downloads_by_status(task_id: int, status: str) -> int:
    db = await get_db()
    try:
        row = await db.execute(
            "SELECT COUNT(*) as cnt FROM downloads WHERE task_id = ? AND status = ?",
            (task_id, status),
        )
        result = await row.fetchone()
        return result["cnt"] if result else 0
    finally:
        await db.close()


async def get_failed_downloads(task_id: int) -> list[dict]:
    db = await get_db()
    try:
        rows = await db.execute(
            "SELECT * FROM downloads WHERE task_id = ? AND status = 'failed'",
            (task_id,),
        )
        results = [dict(r) for r in await rows.fetchall()]
        return results
    finally:
        await db.close()


# --- Settings ---

async def get_settings() -> dict:
    db = await get_db()
    try:
        rows = await db.execute("SELECT key, value FROM settings")
        results = {r["key"]: r["value"] for r in await rows.fetchall()}
        return results
    finally:
        await db.close()


async def update_setting(key: str, value: str):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value),
        )
        await db.commit()
    finally:
        await db.close()
