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
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        task_manager.unregister_progress_callback(progress_callback)
        if ws in active_connections:
            active_connections.remove(ws)
