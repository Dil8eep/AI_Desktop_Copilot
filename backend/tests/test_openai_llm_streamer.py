from pydantic import SecretStr
from pytest import MonkeyPatch

from app.infrastructure.user_llm_runtime import UserLlmRuntime
from app.main import build_container
from app.settings import Settings


def test_configured_backend_builds_the_user_scoped_llm_runtime() -> None:
    container = build_container(
        Settings(
            llm_provider="openai",
            openai_api_key=SecretStr("test-key"),
            openai_model="gpt-4.1-mini",
        )
    )

    assert isinstance(container.llm_streamer, UserLlmRuntime)


def test_settings_accepts_the_standard_openai_environment_variable(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    settings = Settings()

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-key"
