"""User-scoped provider routing for streaming and structured resume parsing."""

import asyncio
import json
from base64 import b64encode
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

from openai import AsyncOpenAI, OpenAIError

from app.application.user_llm_credential_service import UserLlmCredentialService
from app.domain.llm import LlmDelta, LlmRequest, LlmStreamError

_COMPATIBLE_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}
_IMAGE_PROVIDERS = frozenset({"openai", "openrouter", "gemini"})


class UserLlmRuntime:
    """Resolve one user's active provider once per operation and route safely."""

    def __init__(
        self, credentials: UserLlmCredentialService, timeout_seconds: float
    ) -> None:
        self._credentials = credentials
        self._timeout_seconds = timeout_seconds

    async def stream(
        self, request: LlmRequest, cancellation_requested: asyncio.Event
    ) -> AsyncIterator[LlmDelta]:
        if request.user_id is None:
            raise LlmStreamError("llm_user_required")
        try:
            resolved = await self._credentials.resolve(request.user_id)
            routed_request = request
            if (
                request.image_bytes is not None
                and resolved.provider not in _IMAGE_PROVIDERS
            ):
                # LiteParse OCR is already embedded in the prompt. Text-only providers
                # receive that extracted content without the original image attachment.
                routed_request = replace(
                    request, image_bytes=None, image_mime_type=None
                )
            if resolved.provider == "openai":
                async for delta in self._stream_openai(
                    resolved.credential,
                    resolved.model,
                    routed_request,
                    cancellation_requested,
                ):
                    yield delta
                return
            if resolved.provider in _COMPATIBLE_BASE_URLS:
                async for delta in self._stream_compatible(
                    resolved.provider,
                    resolved.credential,
                    resolved.model,
                    routed_request,
                    cancellation_requested,
                ):
                    yield delta
                return
            if resolved.provider == "ollama_cloud":
                async for delta in self._stream_ollama(
                    resolved.credential,
                    resolved.model,
                    routed_request,
                    cancellation_requested,
                ):
                    yield delta
                return
            raise LlmStreamError("provider_not_supported")
        except LlmStreamError:
            raise
        except ValueError as error:
            if str(error) == "llm_configuration_required":
                raise LlmStreamError("llm_configuration_required") from error
            raise LlmStreamError("llm_provider_request_failed") from error
        except (OpenAIError, RuntimeError) as error:
            raise LlmStreamError("llm_provider_request_failed") from error

    async def parse(self, user_id: str, resume_text: str) -> dict[str, Any]:
        prompt = self._resume_prompt(resume_text)
        parts: list[str] = []
        request = LlmRequest(session_id=uuid4(), prompt=prompt, user_id=user_id)
        async for delta in self.stream(request, asyncio.Event()):
            parts.append(delta.text)
        raw = "".join(parts).strip()
        if raw.startswith("```"):
            raw = raw.removeprefix("```json").removeprefix("```")
            raw = raw.removesuffix("```").strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("resume_profile_invalid_json")
        return parsed

    async def _stream_openai(
        self,
        credential: str,
        model: str,
        request: LlmRequest,
        cancellation_requested: asyncio.Event,
    ) -> AsyncIterator[LlmDelta]:
        client = AsyncOpenAI(api_key=credential, timeout=self._timeout_seconds)
        input_value: Any = self._responses_input(request)
        stream = cast(
            AsyncIterator[Any],
            await client.responses.create(model=model, input=input_value, stream=True),
        )
        async for event in stream:
            if cancellation_requested.is_set():
                return
            if getattr(event, "type", None) == "response.output_text.delta":
                text = getattr(event, "delta", None)
                if isinstance(text, str) and text:
                    yield LlmDelta(text)

    async def _stream_compatible(
        self,
        provider: str,
        credential: str,
        model: str,
        request: LlmRequest,
        cancellation_requested: asyncio.Event,
    ) -> AsyncIterator[LlmDelta]:
        client = AsyncOpenAI(
            api_key=credential,
            base_url=_COMPATIBLE_BASE_URLS[provider],
            timeout=self._timeout_seconds,
        )
        stream = await client.chat.completions.create(
            model=model,
            messages=cast(Any, [self._chat_message(request)]),
            stream=True,
        )
        async for chunk in stream:
            if cancellation_requested.is_set():
                return
            text = chunk.choices[0].delta.content if chunk.choices else None
            if isinstance(text, str) and text:
                yield LlmDelta(text)

    async def _stream_ollama(
        self,
        credential: str,
        model: str,
        request: LlmRequest,
        cancellation_requested: asyncio.Event,
    ) -> AsyncIterator[LlmDelta]:
        try:
            from ollama import AsyncClient
        except ImportError as error:
            raise LlmStreamError("ollama_client_unavailable") from error
        client = AsyncClient(
            host="https://ollama.com",
            headers={"Authorization": f"Bearer {credential}"},
        )
        stream = await client.chat(
            model=model,
            messages=[{"role": "user", "content": request.prompt}],
            stream=True,
        )
        async for part in stream:
            if cancellation_requested.is_set():
                return
            text = getattr(getattr(part, "message", None), "content", None)
            if isinstance(text, str) and text:
                yield LlmDelta(text)

    @staticmethod
    def _responses_input(request: LlmRequest) -> Any:
        if request.image_bytes is None or request.image_mime_type is None:
            return request.prompt
        data_url = (
            f"data:{request.image_mime_type};base64,"
            f"{b64encode(request.image_bytes).decode('ascii')}"
        )
        return [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": request.prompt},
                    {"type": "input_image", "image_url": data_url, "detail": "high"},
                ],
            }
        ]

    @staticmethod
    def _chat_message(request: LlmRequest) -> dict[str, Any]:
        if request.image_bytes is None or request.image_mime_type is None:
            return {"role": "user", "content": request.prompt}
        data_url = (
            f"data:{request.image_mime_type};base64,"
            f"{b64encode(request.image_bytes).decode('ascii')}"
        )
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": request.prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }

    @staticmethod
    def _resume_prompt(resume_text: str) -> str:
        return (
            "Extract this resume into valid JSON. Detect headings dynamically and "
            "preserve all meaningful information. Use candidate, sections, "
            "additional_sections, and summary. Normalize equivalent headings. "
            "Do not invent values. Return JSON only, without markdown.\n\n"
            f"Resume text:\n{resume_text}"
        )
