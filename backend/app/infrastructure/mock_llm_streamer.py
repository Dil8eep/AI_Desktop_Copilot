"""Deterministic non-blocking LLM adapter for development and tests."""

import asyncio
from collections.abc import AsyncIterator

from app.domain.llm import LlmDelta, LlmRequest


class MockLlmStreamer:
    """Streams fixed deltas and reacts cooperatively to cancellation."""

    def __init__(self, token_delay_seconds: float) -> None:
        self._token_delay_seconds = token_delay_seconds

    async def stream(
        self, request: LlmRequest, cancellation_requested: asyncio.Event
    ) -> AsyncIterator[LlmDelta]:
        """Yield test-only deltas without blocking the event loop."""

        del request
        for delta in ("Mock", " streaming", " response", "."):
            try:
                await asyncio.wait_for(
                    cancellation_requested.wait(), timeout=self._token_delay_seconds
                )
                return
            except TimeoutError:
                pass
            if cancellation_requested.is_set():
                return
            yield LlmDelta(text=delta)
