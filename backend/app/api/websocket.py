"""FastAPI adapter for concurrent, versioned desktop WebSocket sessions."""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from fastapi import WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from app.application.session_service import SessionService
from app.domain.audio import SpeechTranscriptionError
from app.domain.ports import (
    AudioIngestor,
    ConversationContext,
    ScreenPerception,
    SystemAudioCapture,
)
from app.domain.protocol import EventEnvelope
from app.infrastructure.auth_service import JwtService
from app.infrastructure.wasapi_loopback_capture import SystemAudioCaptureError

_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_AUDIO_CHUNK_BYTES = 64 * 1024
_IMAGE_MIME_TYPES = {"image/jpeg", "image/png"}
_AUDIO_MIME_TYPE = "audio/pcm;codec=s16le"


def _error_event(
    session_id: UUID, code: str, request_id: UUID | None = None
) -> EventEnvelope:
    return EventEnvelope.create(
        event="protocol.error",
        session_id=session_id,
        request_id=request_id,
        payload={"code": code},
    )


def _valid_binary_payload(event: EventEnvelope, data: bytes) -> str | None:
    """Return a typed protocol error code if a binary event is unsafe."""

    declared_length = event.payload.get("byteLength")
    mime_type = event.payload.get("mimeType")
    if declared_length != len(data) or not isinstance(mime_type, str):
        return "invalid_binary_metadata"
    if event.event == "screen.capture":
        if mime_type not in _IMAGE_MIME_TYPES:
            return "unsupported_image_type"
        if len(data) > _MAX_IMAGE_BYTES:
            return "image_too_large"
    if event.event == "audio.chunk":
        if mime_type != _AUDIO_MIME_TYPE:
            return "unsupported_audio_type"
        if len(data) > _MAX_AUDIO_CHUNK_BYTES:
            return "audio_chunk_too_large"
    return None


def create_websocket_endpoint(
    session_service: SessionService,
    perception_service: ScreenPerception,
    audio_ingest_service: AudioIngestor,
    expected_token: str,
    context_factory: Callable[[], ConversationContext],
    automatic_responses_enabled: bool,
    console_transcript_logging: bool,
    system_audio_capture_factory: Callable[[], SystemAudioCapture],
    jwt_service: JwtService | None = None,
) -> Callable[[WebSocket], Awaitable[None]]:
    """Create an authenticated endpoint with per-connection task ownership."""

    async def websocket_endpoint(websocket: WebSocket) -> None:
        if websocket.headers.get("x-copilot-token") != expected_token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        user_id: str | None = None
        if jwt_service is not None:
            authorization = websocket.headers.get("authorization", "")
            if not authorization.startswith("Bearer "):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            try:
                user_id = jwt_service.verify_access_token(authorization[7:])
            except Exception:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

        await websocket.accept()
        connection_session_id = uuid4()
        context = context_factory()
        system_audio_capture = system_audio_capture_factory()
        outbound: asyncio.Queue[EventEnvelope | None] = asyncio.Queue()
        active_streams: dict[UUID, asyncio.Task[None]] = {}
        automatic_response_sessions: dict[UUID, UUID] = {}
        processing_tasks: set[asyncio.Task[None]] = set()
        pending_binary: EventEnvelope | None = None
        system_audio_task: asyncio.Task[None] | None = None

        async def sender() -> None:
            while True:
                response = await outbound.get()
                if response is None:
                    return
                await websocket.send_json(
                    response.model_dump(by_alias=True, mode="json")
                )

        async def stream_session(
            event: EventEnvelope, source_session_id: UUID | None = None
        ) -> None:
            ai_output_started = False
            try:
                async for response in session_service.stream(
                    event, context.get_screen_image(), user_id
                ):
                    if (
                        console_transcript_logging
                        and source_session_id is not None
                        and response.event == "llm.token"
                    ):
                        delta = response.payload.get("delta")
                        if isinstance(delta, str):
                            print(
                                "AI: " if not ai_output_started else "",
                                end=delta,
                                flush=True,
                            )
                            ai_output_started = True
                    await outbound.put(response)
            finally:
                if console_transcript_logging and ai_output_started:
                    print(flush=True)
                active_streams.pop(event.session_id, None)
                if (
                    source_session_id is not None
                    and automatic_response_sessions.get(source_session_id)
                    == event.session_id
                ):
                    automatic_response_sessions.pop(source_session_id, None)

        async def start_automatic_response(source_event: EventEnvelope) -> None:
            text = source_event.payload.get("text")
            source = source_event.payload.get("source")
            if not isinstance(text, str) or not isinstance(source, str):
                return
            context.record_transcript(text, source)
            if console_transcript_logging:
                print(f"Speaker: {text}", flush=True)
            # System audio may contain another meeting participant. Keep it as
            # transcript context, but require an explicit user action before an
            # LLM response is generated from it.
            if not automatic_responses_enabled or source == "system-audio":
                return
            previous_session_id = automatic_response_sessions.get(
                source_event.session_id
            )
            if previous_session_id is not None:
                await session_service.cancel_session(previous_session_id)
            response_session_id = uuid4()
            try:
                prompt = context.build_prompt()
            except ValueError as error:
                await outbound.put(
                    _error_event(
                        source_event.session_id,
                        str(error),
                        source_event.request_id,
                    )
                )
                return
            response_event = EventEnvelope.create(
                event="session.start",
                session_id=response_session_id,
                request_id=source_event.request_id,
                payload={"prompt": prompt},
            )
            automatic_response_sessions[source_event.session_id] = response_session_id
            active_streams[response_session_id] = asyncio.create_task(
                stream_session(response_event, source_event.session_id),
                name=f"copilot-auto-response-{response_session_id}",
            )

        async def dispatch_responses(responses: tuple[EventEnvelope, ...]) -> None:
            for response in responses:
                if response.event == "context.updated":
                    screen_text = response.payload.get("screenText")
                    if isinstance(screen_text, str):
                        context.update_screen(screen_text)
                        # Screen analysis is an explicit button action, so solve it
                        # independently of automatic speech-response preferences.
                        if screen_text.strip():
                            previous = automatic_response_sessions.get(
                                response.session_id
                            )
                            if previous is not None:
                                await session_service.cancel_session(previous)
                            try:
                                prompt = context.build_screen_prompt()
                            except ValueError as error:
                                await outbound.put(
                                    _error_event(
                                        response.session_id,
                                        str(error),
                                        response.request_id,
                                    )
                                )
                            else:
                                response_session_id = uuid4()
                                response_event = EventEnvelope.create(
                                    event="session.start",
                                    session_id=response_session_id,
                                    request_id=response.request_id,
                                    payload={"prompt": prompt},
                                )
                                automatic_response_sessions[response.session_id] = (
                                    response_session_id
                                )
                                active_streams[response_session_id] = (
                                    asyncio.create_task(
                                        stream_session(
                                            response_event, response.session_id
                                        ),
                                        name="copilot-screen-response",
                                    )
                                )
                await outbound.put(response)
                if response.event == "speech.final":
                    await start_automatic_response(response)

        async def process_binary(event: EventEnvelope, data: bytes) -> None:
            try:
                error_code = _valid_binary_payload(event, data)
                if error_code is not None:
                    await outbound.put(
                        _error_event(event.session_id, error_code, event.request_id)
                    )
                    return
                if event.event == "screen.capture":
                    mime_type = event.payload.get("mimeType")
                    if isinstance(mime_type, str):
                        context.update_screen_image(data, mime_type)
                    responses = await perception_service.analyze_screen(event, data)
                else:
                    responses = await audio_ingest_service.ingest(event, data)
                await dispatch_responses(responses)
            except (SpeechTranscriptionError, ValueError) as error:
                await outbound.put(
                    _error_event(event.session_id, str(error), event.request_id)
                )
            finally:
                processing_tasks.discard(asyncio.current_task())

        async def capture_system_audio(event: EventEnvelope) -> None:
            try:
                await system_audio_capture.start()
                await outbound.put(
                    EventEnvelope.create(
                        event="system_audio.started",
                        session_id=event.session_id,
                        request_id=event.request_id,
                        payload={"source": "system-audio"},
                    )
                )
                while True:
                    pcm_s16le = await system_audio_capture.read_pcm16le()
                    if not pcm_s16le:
                        continue
                    audio_event = EventEnvelope.create(
                        event="audio.chunk",
                        session_id=event.session_id,
                        request_id=event.request_id,
                        payload={
                            "mimeType": _AUDIO_MIME_TYPE,
                            "sampleRateHz": 16_000,
                            "byteLength": len(pcm_s16le),
                        },
                    )
                    try:
                        responses = await audio_ingest_service.ingest(
                            audio_event, pcm_s16le, source="system-audio"
                        )
                    except SpeechTranscriptionError as error:
                        await outbound.put(
                            _error_event(
                                audio_event.session_id,
                                error.code,
                                audio_event.request_id,
                            )
                        )
                        continue
                    await dispatch_responses(responses)
            except SystemAudioCaptureError as error:
                await outbound.put(
                    _error_event(event.session_id, str(error), event.request_id)
                )
            except asyncio.CancelledError:
                raise
            finally:
                await system_audio_capture.stop()
                await outbound.put(
                    EventEnvelope.create(
                        event="system_audio.stopped",
                        session_id=event.session_id,
                        request_id=event.request_id,
                        payload={"source": "system-audio"},
                    )
                )

        def start_binary_processing(event: EventEnvelope, data: bytes) -> None:
            task = asyncio.create_task(
                process_binary(event, data), name=f"copilot-{event.event}"
            )
            processing_tasks.add(task)

        sender_task = asyncio.create_task(sender(), name="desktop-websocket-sender")
        await outbound.put(
            EventEnvelope.create(
                event="system.ready",
                session_id=connection_session_id,
                payload={"protocolVersion": "1.0"},
            )
        )

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                data = message.get("bytes")
                if data is not None:
                    if pending_binary is None:
                        await outbound.put(
                            _error_event(
                                connection_session_id, "unexpected_binary_frame"
                            )
                        )
                        continue
                    event = pending_binary
                    pending_binary = None
                    start_binary_processing(event, data)
                    continue
                raw_event = message.get("text")
                if raw_event is None:
                    await outbound.put(
                        _error_event(
                            connection_session_id, "unsupported_websocket_frame"
                        )
                    )
                    continue
                try:
                    event = EventEnvelope.model_validate_json(raw_event)
                except ValidationError:
                    await outbound.put(
                        _error_event(connection_session_id, "invalid_protocol_envelope")
                    )
                    continue

                if event.event == "session.start":
                    prompt = event.payload.get("prompt")
                    screen_text = event.payload.get("screenText")
                    candidate_profile = event.payload.get("candidateProfile")
                    include_candidate_profile = event.payload.get(
                        "includeCandidateProfile", False
                    )
                    if isinstance(screen_text, str):
                        context.update_screen(screen_text)
                    if isinstance(candidate_profile, dict):
                        context.update_candidate_profile(candidate_profile)
                    if isinstance(prompt, str) and prompt.strip():
                        event = EventEnvelope.create(
                            event="session.start",
                            session_id=event.session_id,
                            request_id=event.request_id,
                            payload={
                                "prompt": context.build_user_prompt(
                                    prompt,
                                    include_candidate_profile
                                    if isinstance(include_candidate_profile, bool)
                                    else False,
                                )
                            },
                        )
                    if event.session_id in active_streams:
                        await outbound.put(
                            _error_event(
                                event.session_id,
                                "session_already_active",
                                event.request_id,
                            )
                        )
                        continue
                    active_streams[event.session_id] = asyncio.create_task(
                        stream_session(event),
                        name=f"copilot-session-{event.session_id}",
                    )
                elif event.event in {"screen.capture", "audio.chunk"}:
                    if pending_binary is not None:
                        await outbound.put(
                            _error_event(
                                event.session_id,
                                "binary_frame_already_pending",
                                event.request_id,
                            )
                        )
                    else:
                        pending_binary = event
                elif event.event == "system_audio.start":
                    if system_audio_task is not None and not system_audio_task.done():
                        await outbound.put(
                            _error_event(
                                event.session_id,
                                "system_audio_already_active",
                                event.request_id,
                            )
                        )
                        continue
                    system_audio_task = asyncio.create_task(
                        capture_system_audio(event), name="copilot-system-audio"
                    )
                elif event.event == "system_audio.stop":
                    if system_audio_task is None or system_audio_task.done():
                        await outbound.put(
                            _error_event(
                                event.session_id,
                                "system_audio_not_active",
                                event.request_id,
                            )
                        )
                        continue
                    system_audio_task.cancel()
                    await asyncio.gather(system_audio_task, return_exceptions=True)
                    system_audio_task = None
                elif event.event == "session.stop":
                    error = await session_service.cancel(event)
                    if error is not None:
                        await outbound.put(error)
                else:
                    await outbound.put(
                        _error_event(
                            event.session_id, "unsupported_command", event.request_id
                        )
                    )
        except WebSocketDisconnect:
            return
        finally:
            if system_audio_task is not None:
                system_audio_task.cancel()
                await asyncio.gather(system_audio_task, return_exceptions=True)
            for session_id in tuple(active_streams):
                await session_service.cancel_session(session_id)
            for task in tuple(active_streams.values()):
                task.cancel()
            for task in tuple(processing_tasks):
                task.cancel()
            await asyncio.gather(*active_streams.values(), return_exceptions=True)
            await asyncio.gather(*processing_tasks, return_exceptions=True)
            sender_task.cancel()
            await asyncio.gather(sender_task, return_exceptions=True)

    return websocket_endpoint
