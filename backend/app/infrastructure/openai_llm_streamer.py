"""OpenAI Responses API adapter for token-by-token multimodal output."""

import asyncio
from base64 import b64encode
from collections.abc import AsyncIterator
from typing import Any, cast

from openai import AsyncOpenAI, OpenAIError

from app.domain.llm import LlmDelta, LlmRequest, LlmStreamError
from app.infrastructure.provider_client_factory import ProviderClientFactory
from app.infrastructure.provider_credential_resolver import CredentialResolutionError


class OpenAiLlmStreamer:
    """Resolve one credential per stream and retain that client until completion."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout_seconds: float,
        client_factory: ProviderClientFactory | None = None,
    ) -> None:
        self._client = (
            AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
            if api_key is not None
            else None
        )
        self._model = model
        self._client_factory = client_factory

    async def stream(
        self, request: LlmRequest, cancellation_requested: asyncio.Event
    ) -> AsyncIterator[LlmDelta]:
        """Yield output-text deltas as soon as the Responses API emits them."""
        input_value: object = request.prompt
        if request.image_bytes is not None and request.image_mime_type is not None:
            image_data_url = (
                f"data:{request.image_mime_type};base64,"
                f"{b64encode(request.image_bytes).decode('ascii')}"
            )
            input_value = [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": request.prompt},
                        {
                            "type": "input_image",
                            "image_url": image_data_url,
                            "detail": "high",
                        },
                    ],
                }
            ]
        try:
            client, model = await self._client_for_stream()
            response_stream = cast(
                AsyncIterator[Any],
                await client.responses.create(
                    model=model,
                    input=cast(Any, input_value),
                    stream=True,
                ),
            )
            async for event in response_stream:
                if cancellation_requested.is_set():
                    return
                if getattr(event, "type", None) != "response.output_text.delta":
                    continue
                text = getattr(event, "delta", None)
                if isinstance(text, str) and text:
                    yield LlmDelta(text=text)
        except (OpenAIError, CredentialResolutionError) as error:
            raise LlmStreamError("openai_stream_failed") from error

    async def _client_for_stream(self) -> tuple[AsyncOpenAI, str]:
        if self._client_factory is not None:
            client, resolved = await self._client_factory.openai()
            return client, resolved.model or self._model
        if self._client is None:
            raise CredentialResolutionError("provider_not_configured")
        return self._client, self._model
