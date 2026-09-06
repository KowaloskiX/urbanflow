from fastapi import WebSocket


class LiveUpdateManager:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def publish(self, event_type: str, payload: dict) -> None:
        message = {"type": event_type, "payload": payload}
        disconnected: list[WebSocket] = []
        for connection in self.connections:
            try:
                await connection.send_json(message)
            except RuntimeError:
                disconnected.append(connection)
        for connection in disconnected:
            self.disconnect(connection)


live_updates = LiveUpdateManager()
