"""User-scoped LLM runtime provider routing regressions."""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from app.application.user_llm_credential_service import ResolvedUserLlmConfiguration
from app.domain.llm import LlmDelta, LlmRequest, LlmStreamError
from app.infrastructure.user_llm_runtime import UserLlmRuntime


class FakeCredentials:
    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.user_ids: list[str] = []

    async def resolve(self, user_id: str) -> ResolvedUserLlmConfiguration:
        self.user_ids.append(user_id)
        return ResolvedUserLlmConfiguration(self.provider, "model-id", "private-key")


class RecordingRuntime(UserLlmRuntime):
    def __init__(self, credentials: FakeCredentials) -> None:
        super().__init__(credentials, 5)  # type: ignore[arg-type]
        self.adapters: list[str] = []
        self.requests: list[LlmRequest] = []

    async def _stream_openai(self, *args: object) -> AsyncIterator[LlmDelta]:
        self.requests.append(
            next(item for item in args if isinstance(item, LlmRequest))
        )
        self.adapters.append("openai")
        yield LlmDelta("ok")

    async def _stream_compatible(
        self, provider: str, *args: object
    ) -> AsyncIterator[LlmDelta]:
        self.requests.append(
            next(item for item in args if isinstance(item, LlmRequest))
        )
        self.adapters.append(provider)
        yield LlmDelta("ok")

    async def _stream_ollama(self, *args: object) -> AsyncIterator[LlmDelta]:
        self.requests.append(
            next(item for item in args if isinstance(item, LlmRequest))
        )
        self.adapters.append("ollama_cloud")
        yield LlmDelta("ok")


class SequencedParseRuntime(UserLlmRuntime):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(FakeCredentials("openai"), 5)  # type: ignore[arg-type]
        self.responses = responses
        self.prompts: list[str] = []

    async def stream(
        self, request: LlmRequest, cancellation_requested: asyncio.Event
    ) -> AsyncIterator[LlmDelta]:
        del cancellation_requested
        self.prompts.append(request.prompt)
        response = self.responses.pop(0)
        if response:
            yield LlmDelta(response)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider", ["openai", "groq", "openrouter", "gemini", "ollama_cloud"]
)
async def test_routes_each_supported_provider_for_authenticated_user(
    provider: str,
) -> None:
    credentials = FakeCredentials(provider)
    runtime = RecordingRuntime(credentials)
    request = LlmRequest(uuid4(), "help", user_id="verified-user")

    deltas = [delta.text async for delta in runtime.stream(request, asyncio.Event())]

    assert deltas == ["ok"]
    assert runtime.adapters == [provider]
    assert credentials.user_ids == ["verified-user"]


@pytest.mark.asyncio
async def test_requires_user_and_uses_ocr_text_for_text_only_provider() -> None:
    runtime = RecordingRuntime(FakeCredentials("groq"))
    with pytest.raises(LlmStreamError, match="llm_user_required"):
        _ = [
            delta.text
            async for delta in runtime.stream(
                LlmRequest(uuid4(), "help"), asyncio.Event()
            )
        ]

    request = LlmRequest(
        uuid4(),
        "solve",
        user_id="verified-user",
        image_bytes=b"image",
        image_mime_type="image/png",
    )
    deltas = [delta.text async for delta in runtime.stream(request, asyncio.Event())]

    assert deltas == ["ok"]
    routed = runtime.requests[-1]
    assert routed.prompt == "solve"
    assert routed.image_bytes is None
    assert routed.image_mime_type is None


@pytest.mark.asyncio
async def test_resume_parse_retries_an_empty_response_once() -> None:
    runtime = SequencedParseRuntime(["", '{"summary": "ready"}'])

    profile = await runtime.parse("verified-user", "resume text")

    assert profile == {"summary": "ready"}
    assert len(runtime.prompts) == 2
    assert "previous response was empty or invalid" in runtime.prompts[1]


@pytest.mark.asyncio
async def test_resume_parse_returns_stable_error_after_invalid_responses() -> None:
    runtime = SequencedParseRuntime(["not-json", "still-not-json"])

    with pytest.raises(ValueError, match="resume_profile_invalid_json"):
        await runtime.parse("verified-user", "resume text")
