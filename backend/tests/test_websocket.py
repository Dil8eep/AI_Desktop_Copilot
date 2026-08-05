from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.infrastructure.auth_service import JwtService
from app.main import create_application
from app.settings import Settings


def _event(
    event: str, session_id: str, request_id: str, payload: dict[str, object]
) -> dict[str, object]:
    return {
        "version": "1.0",
        "event": event,
        "sessionId": session_id,
        "requestId": request_id,
        "timestamp": "2026-07-29T00:00:00Z",
        "payload": payload,
    }


_JWT_SECRET = "test-websocket-secret-that-is-over-32-bytes"


def _headers(local_token: str = "test-token") -> dict[str, str]:
    access_token = JwtService(_JWT_SECRET, 15).issue_access_token(str(uuid4()))
    return {
        "x-copilot-token": local_token,
        "authorization": f"Bearer {access_token}",
    }


def _client(token_delay_ms: int = 1) -> TestClient:
    return TestClient(
        create_application(
            Settings(
                local_auth_token="test-token",
                jwt_secret=_JWT_SECRET,
                credential_master_key=None,
                llm_provider="mock",
                mock_llm_token_delay_ms=token_delay_ms,
            )
        )
    )


def _production_client() -> TestClient:
    settings = Settings(
        local_auth_token="test-token",
        jwt_secret=_JWT_SECRET,
        credential_master_key=None,
        llm_provider="mock",
        mock_llm_token_delay_ms=1,
    )
    # Exercise the production WebSocket composition without starting external
    # database listeners that are unrelated to this handshake contract.
    settings.environment = "production"
    return TestClient(create_application(settings))


def test_session_start_streams_multiple_deltas_then_completion() -> None:
    session_id = str(uuid4())
    request_id = str(uuid4())

    with _client() as client:
        with client.websocket_connect("/ws", headers=_headers()) as websocket:
            assert websocket.receive_json()["event"] == "system.ready"
            websocket.send_json(
                _event("session.start", session_id, request_id, {"prompt": "Help me"})
            )
            events: list[dict[str, object]] = []
            while not events or events[-1]["event"] != "llm.completed":
                events.append(websocket.receive_json())

    deltas = [
        cast(dict[str, str], item["payload"])["delta"]
        for item in events
        if item["event"] == "llm.token"
    ]
    assert deltas == ["Mock", " streaming", " response", "."]
    assert events[-1]["payload"] == {"reason": "completed"}


def test_session_stop_cancels_an_active_stream() -> None:
    session_id = str(uuid4())

    with _client(token_delay_ms=100) as client:
        with client.websocket_connect("/ws", headers=_headers()) as websocket:
            websocket.receive_json()
            websocket.send_json(
                _event(
                    "session.start", session_id, str(uuid4()), {"prompt": "Cancel me"}
                )
            )
            websocket.send_json(_event("session.stop", session_id, str(uuid4()), {}))
            completed = websocket.receive_json()

    assert completed["event"] == "llm.completed"
    assert completed["payload"] == {"reason": "cancelled"}


def test_invalid_session_payload_returns_typed_protocol_error() -> None:
    with _client() as client:
        with client.websocket_connect("/ws", headers=_headers()) as websocket:
            websocket.receive_json()
            websocket.send_json(_event("session.start", str(uuid4()), str(uuid4()), {}))
            error = websocket.receive_json()

    assert error["event"] == "protocol.error"
    assert error["payload"] == {"code": "invalid_session_start"}


def test_websocket_requires_the_per_launch_local_token() -> None:
    with _client() as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/ws", headers=_headers("wrong-token")):
                pass

    assert error.value.code == 1008


def test_websocket_requires_a_valid_user_access_token() -> None:
    with _client() as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(
                "/ws", headers={"x-copilot-token": "test-token"}
            ):
                pass

    assert error.value.code == 1008


def test_capture_binary_frame_validates_its_declared_media_type() -> None:
    session_id = str(uuid4())
    request_id = str(uuid4())

    with _client() as client:
        with client.websocket_connect("/ws", headers=_headers()) as websocket:
            websocket.receive_json()
            websocket.send_json(
                _event(
                    "screen.capture",
                    session_id,
                    request_id,
                    {"mimeType": "image/gif", "byteLength": 3},
                )
            )
            websocket.send_bytes(b"gif")
            error = websocket.receive_json()

    assert error["event"] == "protocol.error"
    assert error["payload"] == {"code": "unsupported_image_type"}


def test_production_websocket_uses_jwt_without_shared_local_token() -> None:
    headers = _headers()
    headers.pop("x-copilot-token")

    with _production_client() as client:
        with client.websocket_connect("/ws", headers=headers) as websocket:
            assert websocket.receive_json()["event"] == "system.ready"


def test_production_websocket_rejects_expired_user_token() -> None:
    expired = JwtService(_JWT_SECRET, -1).issue_access_token(str(uuid4()))

    with _production_client() as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(
                "/ws", headers={"authorization": f"Bearer {expired}"}
            ):
                pass

    assert error.value.code == 1008


def test_audio_chunk_rejects_unknown_capture_source() -> None:
    session_id = str(uuid4())

    with _client() as client:
        with client.websocket_connect("/ws", headers=_headers()) as websocket:
            websocket.receive_json()
            websocket.send_json(
                _event(
                    "audio.chunk",
                    session_id,
                    str(uuid4()),
                    {
                        "mimeType": "audio/pcm;codec=s16le",
                        "sampleRateHz": 16_000,
                        "source": "remote-device",
                        "byteLength": 2,
                    },
                )
            )
            websocket.send_bytes(b"00")
            error = websocket.receive_json()

    assert error["event"] == "protocol.error"
    assert error["payload"] == {"code": "unsupported_audio_source"}
