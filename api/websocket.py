import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    def add(self, ws: WebSocket):
        self._connections.append(ws)

    def remove(self, ws: WebSocket):
        try:
            self._connections.remove(ws)
        except ValueError:
            pass


manager = ConnectionManager()


@router.websocket("/ws/progress")
async def websocket_progress(ws: WebSocket):
    await ws.accept()
    manager.add(ws)

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
            return False
        return True

    from app import task_manager
    task_manager.register_progress_callback(progress_callback)

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                try:
                    await ws.send_json({"type": "pong"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        task_manager.unregister_progress_callback(progress_callback)
        manager.remove(ws)