"""WebSocket progress channel.

One connection from the web UI receives every task-level and file-level
progress event.  The client sends ``{"type": "ping"}`` heartbeats and receives
``{"type": "pong"}`` so half-open connections are detected quickly.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

HEARTBEAT_INTERVAL = 25.0


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.append(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            try:
                self._connections.remove(ws)
            except ValueError:
                pass

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


@router.websocket("/ws/progress")
async def websocket_progress(ws: WebSocket) -> None:
    await ws.accept()
    await manager.add(ws)

    from app import task_manager

    send_lock = asyncio.Lock()

    async def listener(payload: dict) -> bool:
        """Forward one event. Returns False so the manager drops dead sockets."""
        async with send_lock:
            try:
                await ws.send_json(payload)
                return True
            except Exception:  # noqa: BLE001 - the socket is gone
                return False

    task_manager.register_progress_callback(listener)

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            async with send_lock:
                try:
                    await ws.send_json({"type": "heartbeat"})
                except Exception:  # noqa: BLE001
                    return

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        await ws.send_json({"type": "hello", "running_tasks": task_manager.running_task_ids})
        while True:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if message.get("type") == "ping":
                async with send_lock:
                    await ws.send_json({"type": "pong"})
            elif message.get("type") == "subscribe":
                await ws.send_json({
                    "type": "subscribed",
                    "running_tasks": task_manager.running_task_ids,
                })
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - the client vanished mid-frame
        pass
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        task_manager.unregister_progress_callback(listener)
        await manager.remove(ws)
