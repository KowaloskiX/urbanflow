from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.live_updates import live_updates

router = APIRouter(tags=["live updates"])


@router.websocket("/live")
async def live(websocket: WebSocket) -> None:
    await live_updates.connect(websocket)
    await websocket.send_json({"type": "connected", "payload": {"status": "ok"}})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        live_updates.disconnect(websocket)
