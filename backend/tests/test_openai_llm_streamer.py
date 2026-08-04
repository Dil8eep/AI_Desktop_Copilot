from pydantic import SecretStr
from pytest import MonkeyPatch

from app.infrastructure.openai_llm_streamer import OpenAiLlmStreamer
from app.main import build_container
from app.settings import Settings


def test_openai_provider_builds_the_openai_streamer() -> None:
    container = build_container(
        Settings(
            llm_provider="openai",
            openai_api_key=SecretStr("test-key"),
            openai_model="gpt-4.1-mini",
        )
    )

    assert isinstance(container.llm_streamer, OpenAiLlmStreamer)

def test_settings_accepts_the_standard_openai_environment_variable(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    settings = Settings()

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-key"