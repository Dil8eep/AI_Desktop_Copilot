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

    async def _stream_openai(self, *args: object) -> AsyncIterator[LlmDelta]:
        del args
        self.adapters.append("openai")
        yield LlmDelta("ok")

    async def _stream_compatible(
        self, provider: str, *args: object
    ) -> AsyncIterator[LlmDelta]:
        del args
        self.adapters.append(provider)
        yield LlmDelta("ok")

    async def _stream_ollama(self, *args: object) -> AsyncIterator[LlmDelta]:
        del args
        self.adapters.append("ollama_cloud")
        yield LlmDelta("ok")


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
async def test_rejects_unbound_user_and_unsupported_image_provider() -> None:
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
    with pytest.raises(LlmStreamError, match="provider_model_image_not_supported"):
        _ = [delta.text async for delta in runtime.stream(request, asyncio.Event())]
