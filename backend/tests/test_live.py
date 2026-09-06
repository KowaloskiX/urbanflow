from fastapi.testclient import TestClient

from app.main import app


def test_websocket_sends_connection_event() -> None:
    with (
        TestClient(app) as client,
        client.websocket_connect("/api/v1/live") as websocket,
    ):
        message = websocket.receive_json()

    assert message == {"type": "connected", "payload": {"status": "ok"}}
