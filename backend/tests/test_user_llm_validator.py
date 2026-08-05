"""Live user LLM validator request-shape and safe-error regressions."""

from typing import Any

import pytest

from app.infrastructure import user_llm_credential_validator as validator_module
from app.infrastructure.user_llm_credential_validator import (
    LiveUserLlmCredentialValidator,
)


class RecordingModels:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def retrieve(self, model: str) -> object:
        self.requests.append({"model": model})
        return object()


class FakeOpenAiClient:
    def __init__(self, models: RecordingModels) -> None:
        self.models = models


class ProviderError(Exception):
    def __init__(self, status_code: int, body: dict[str, object]) -> None:
        self.status_code = status_code
        self.body = body


@pytest.mark.asyncio
async def test_openai_validation_checks_key_and_model_without_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = RecordingModels()
    monkeypatch.setattr(
        validator_module,
        "AsyncOpenAI",
        lambda **_kwargs: FakeOpenAiClient(models),
    )

    result = await LiveUserLlmCredentialValidator().validate(
        "openai", "valid-key", "gpt-model"
    )

    assert result.valid is True
    assert models.requests == [{"model": "gpt-model"}]


def test_openai_errors_distinguish_key_model_and_request() -> None:
    classify = LiveUserLlmCredentialValidator._safe_error_code

    assert classify(ProviderError(401, {})) == "provider_authentication_failed"
    assert (
        classify(ProviderError(400, {"code": "model_not_found", "param": "model"}))
        == "provider_model_not_available"
    )
    assert classify(ProviderError(400, {})) == "provider_request_invalid"
