"""FastAPI composition root for AI Desktop Copilot."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.admin import create_admin_router
from app.api.auth import create_auth_router
from app.api.auth_dependencies import require_user_id
from app.api.security import RateLimitMiddleware, SecurityHeadersMiddleware
from app.api.user_llm import create_user_llm_router
from app.api.websocket import create_websocket_endpoint
from app.application.audio_ingest_service import AudioIngestService
from app.application.context_service import ContextService
from app.application.perception_service import PerceptionService
from app.application.provider_credential_service import ProviderCredentialService
from app.application.resume_service import ResumeService
from app.application.session_service import SessionService
from app.application.user_llm_credential_service import UserLlmCredentialService
from app.domain.llm import LlmStreamError
from app.domain.ports import (
    ConversationContext,
    LlmStreamer,
    ResumeProfileParser,
    SessionRepository,
    SpeechTranscriber,
    SystemAudioCapture,
)
from app.infrastructure.admin_repository import AdminRepository
from app.infrastructure.auth_service import JwtService
from app.infrastructure.credential_cipher import CredentialCipher
from app.infrastructure.credential_invalidation_listener import (
    CredentialInvalidationListener,
)
from app.infrastructure.groq_whisper_transcriber import (
    GroqWhisperTranscriber,
    UnavailableSpeechTranscriber,
)
from app.infrastructure.in_memory_session_repository import InMemorySessionRepository
from app.infrastructure.liteparse_screen_analyzer import LiteParseScreenAnalyzer
from app.infrastructure.mock_llm_streamer import MockLlmStreamer
from app.infrastructure.profile_repository import ProfileRepository
from app.infrastructure.provider_client_factory import ProviderClientFactory
from app.infrastructure.provider_credential_repository import (
    ProviderCredentialRepository,
)
from app.infrastructure.provider_credential_resolver import (
    CredentialResolutionError,
    ProviderCredentialResolver,
)
from app.infrastructure.provider_credential_validator import (
    LiveProviderCredentialValidator,
)
from app.infrastructure.silero_vad_segmenter import SileroVadSegmenter
from app.infrastructure.user_llm_credential_repository import (
    UserLlmCredentialRepository,
)
from app.infrastructure.user_llm_credential_validator import (
    LiveUserLlmCredentialValidator,
)
from app.infrastructure.user_llm_runtime import UserLlmRuntime
from app.infrastructure.user_repository import UserRepository
from app.infrastructure.wasapi_loopback_capture import WasapiLoopbackCapture
from app.settings import Settings


@dataclass(frozen=True)
class ApplicationContainer:
    """Explicit dependencies built once for each FastAPI application."""

    settings: Settings
    sessions: SessionRepository
    llm_streamer: LlmStreamer
    session_service: SessionService
    perception_service: PerceptionService
    resume_service: ResumeService
    resume_parser: ResumeProfileParser | None
    profile_repository: ProfileRepository
    admin_repository: AdminRepository
    credential_service: ProviderCredentialService | None
    user_llm_credential_service: UserLlmCredentialService | None
    credential_resolver: ProviderCredentialResolver
    credential_invalidation_listener: CredentialInvalidationListener | None
    user_repository: UserRepository
    jwt_service: JwtService
    audio_ingest_service: AudioIngestService
    context_factory: Callable[[], ConversationContext]
    system_audio_capture_factory: Callable[[], SystemAudioCapture]


def build_container(settings: Settings) -> ApplicationContainer:
    """Wire provider adapters and runtime credential resolution."""

    sessions = InMemorySessionRepository()
    openai_key = (
        settings.openai_api_key.get_secret_value()
        if settings.openai_api_key is not None
        else ""
    )
    groq_key = (
        settings.groq_api_key.get_secret_value()
        if settings.groq_api_key is not None
        else ""
    )
    credential_repository: ProviderCredentialRepository | None = None
    credential_cipher: CredentialCipher | None = None
    if settings.credential_master_key is not None:
        credential_repository = ProviderCredentialRepository(settings.database_url)
        credential_cipher = CredentialCipher(
            settings.credential_master_key.get_secret_value()
        )
    credential_resolver = ProviderCredentialResolver(
        credential_repository,
        credential_cipher,
        {
            "openai": (openai_key, settings.openai_model),
            "groq": (groq_key, settings.groq_whisper_model),
        },
        settings.credential_cache_seconds,
    )
    client_factory = ProviderClientFactory(
        credential_resolver, settings.llm_timeout_seconds
    )
    credential_service: ProviderCredentialService | None = None
    user_llm_credential_service: UserLlmCredentialService | None = None
    credential_invalidation_listener: CredentialInvalidationListener | None = None
    if credential_repository is not None and credential_cipher is not None:
        credential_service = ProviderCredentialService(
            credential_repository,
            LiveProviderCredentialValidator(),
            credential_cipher,
            credential_resolver,
        )
        user_llm_credential_service = UserLlmCredentialService(
            UserLlmCredentialRepository(settings.database_url),
            LiveUserLlmCredentialValidator(settings.llm_timeout_seconds),
            credential_cipher,
        )
        credential_invalidation_listener = CredentialInvalidationListener(
            settings.database_url, credential_resolver
        )

    llm_streamer: LlmStreamer
    if user_llm_credential_service is not None:
        llm_streamer = UserLlmRuntime(
            user_llm_credential_service, settings.llm_timeout_seconds
        )
    else:
        llm_streamer = MockLlmStreamer(
            token_delay_seconds=settings.mock_llm_token_delay_ms / 1_000
        )
    perception_service = PerceptionService(LiteParseScreenAnalyzer())
    resume_service = ResumeService(
        upload_directory=Path(settings.resume_upload_directory),
        max_file_bytes=settings.resume_max_file_bytes,
    )
    profile_repository = ProfileRepository(settings.database_url)
    admin_repository = AdminRepository(settings.database_url)
    user_repository = UserRepository(settings.database_url)
    jwt_service = JwtService(
        settings.jwt_secret,
        settings.jwt_access_token_minutes,
        settings.jwt_refresh_token_days,
    )
    resume_parser = (
        UserLlmRuntime(user_llm_credential_service, settings.llm_timeout_seconds)
        if user_llm_credential_service is not None
        else None
    )
    transcriber: SpeechTranscriber
    groq_runtime_available = bool(groq_key) or credential_repository is not None
    if settings.speech_provider == "groq" and groq_runtime_available:
        transcriber = GroqWhisperTranscriber(
            api_key=None,
            model=settings.groq_whisper_model,
            timeout_seconds=settings.speech_timeout_seconds,
            client_factory=client_factory,
        )
    else:
        transcriber = UnavailableSpeechTranscriber()
    audio_ingest_service = AudioIngestService(SileroVadSegmenter(), transcriber)

    def context_factory() -> ConversationContext:
        return ContextService(
            max_transcript_characters=settings.context_transcript_characters,
            max_screen_characters=settings.context_screen_characters,
        )

    return ApplicationContainer(
        settings=settings,
        sessions=sessions,
        llm_streamer=llm_streamer,
        session_service=SessionService(sessions, llm_streamer),
        perception_service=perception_service,
        resume_service=resume_service,
        resume_parser=resume_parser,
        profile_repository=profile_repository,
        admin_repository=admin_repository,
        credential_service=credential_service,
        user_llm_credential_service=user_llm_credential_service,
        credential_resolver=credential_resolver,
        credential_invalidation_listener=credential_invalidation_listener,
        user_repository=user_repository,
        jwt_service=jwt_service,
        audio_ingest_service=audio_ingest_service,
        context_factory=context_factory,
        system_audio_capture_factory=WasapiLoopbackCapture,
    )


def create_application(settings: Settings | None = None) -> FastAPI:
    """Create an independently testable FastAPI application instance."""

    resolved_settings = settings or Settings()
    container = build_container(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        listener = container.credential_invalidation_listener
        if listener is not None:
            await listener.start()
        try:
            yield
        finally:
            if listener is not None:
                await listener.stop()

    application = FastAPI(
        title="AI Desktop Copilot Backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=container.settings.parsed_allowed_hosts,
    )
    if container.settings.force_https:
        application.add_middleware(HTTPSRedirectMiddleware)
    application.add_middleware(
        RateLimitMiddleware,
        login_limit=container.settings.login_rate_limit_per_minute,
        credential_limit=container.settings.credential_rate_limit_per_minute,
    )
    application.add_middleware(
        SecurityHeadersMiddleware,
        production=container.settings.environment == "production",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=container.settings.parsed_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Cache-Control",
            "Content-Type",
            "Pragma",
            "X-Filename",
        ],
    )
    application.include_router(
        create_auth_router(container.user_repository, container.jwt_service)
    )
    application.include_router(
        create_admin_router(
            container.user_repository,
            container.jwt_service,
            container.admin_repository,
            container.settings,
            container.credential_service,
        )
    )
    application.include_router(
        create_user_llm_router(
            container.jwt_service,
            container.user_llm_credential_service,
        )
    )

    @application.get("/health")
    @application.get("/health/live")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": container.settings.llm_provider}

    @application.get("/health/ready")
    async def readiness() -> JSONResponse:
        try:
            await container.admin_repository.ping()
        except Exception:
            return JSONResponse(
                {"status": "not_ready", "database": "unavailable"},
                status_code=503,
            )
        return JSONResponse({"status": "ready", "database": "available"})

    @application.post("/api/resume/upload")
    async def upload_resume(
        request: Request, authorization: str | None = Header(default=None)
    ) -> JSONResponse:
        user_id = require_user_id(authorization, container.jwt_service)
        filename = request.headers.get("x-filename", "resume.pdf")
        content_type = request.headers.get("content-type", "")
        if content_type and "application/pdf" not in content_type:
            return JSONResponse({"error": "resume_pdf_required"}, status_code=415)
        try:
            upload = await container.resume_service.upload(
                user_id, filename, await request.body()
            )
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        return JSONResponse(
            {
                "status": "uploaded",
                "uploadId": str(upload.upload_id),
                "filename": upload.filename,
                "sizeBytes": upload.size_bytes,
            },
            status_code=201,
        )

    @application.post("/api/resume/parse")
    async def parse_resume(
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        user_id = require_user_id(authorization, container.jwt_service)
        if container.resume_parser is None:
            return JSONResponse(
                {"error": "llm_configuration_required"}, status_code=422
            )
        try:
            profile = await container.resume_service.parse_profile(
                user_id, container.resume_parser
            )
        except (ValueError, LlmStreamError, CredentialResolutionError) as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        await container.profile_repository.save(user_id, profile)
        await container.resume_service.discard_upload(user_id)
        return JSONResponse({"status": "parsed", "profile": profile})

    @application.get("/api/profile")
    async def get_profile(
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        user_id = require_user_id(authorization, container.jwt_service)
        profile = await container.profile_repository.get(user_id)
        return {"profile": profile}

    application.add_api_websocket_route(
        "/ws",
        create_websocket_endpoint(
            container.session_service,
            container.perception_service,
            container.audio_ingest_service,
            container.settings.local_auth_token,
            container.context_factory,
            container.settings.auto_respond_to_speech,
            container.settings.console_transcript_logging,
            container.system_audio_capture_factory,
            container.jwt_service,
            require_local_token=container.settings.environment != "production",
        ),
    )
    return application


app = create_application()
