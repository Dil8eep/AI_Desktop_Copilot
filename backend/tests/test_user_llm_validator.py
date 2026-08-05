"""Live user LLM validator request-shape and safe-error regressions."""

from typing import Any

import pytest

from app.infrastructure import user_llm_credential_validator as validator_module
from app.infrastructure.user_llm_credential_validator import (
    LiveUserLlmCredentialValidator,
)


class RecordingResponses:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return object()


class FakeOpenAiClient:
    def __init__(self, responses: RecordingResponses) -> None:
        self.responses = responses


class ProviderError(Exception):
    def __init__(self, status_code: int, body: dict[str, object]) -> None:
        self.status_code = status_code
        self.body = body


@pytest.mark.asyncio
async def test_openai_validation_uses_normal_responses_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = RecordingResponses()
    monkeypatch.setattr(
        validator_module,
        "AsyncOpenAI",
        lambda **_kwargs: FakeOpenAiClient(responses),
    )

    result = await LiveUserLlmCredentialValidator().validate(
        "openai", "valid-key", "gpt-model"
    )

    assert result.valid is True
    assert responses.requests == [{"model": "gpt-model", "input": "Reply with OK."}]


def test_openai_errors_distinguish_key_model_and_request() -> None:
    classify = LiveUserLlmCredentialValidator._safe_error_code

    assert classify(ProviderError(401, {})) == "provider_authentication_failed"
    assert (
        classify(ProviderError(400, {"code": "model_not_found", "param": "model"}))
        == "provider_model_not_available"
    )
    assert classify(ProviderError(400, {})) == "provider_request_invalid"
