from __future__ import annotations

from dataclasses import replace

import pytest

from src.config import LLMConfigurationError, load_settings
from src.llm import MockLLMClient, get_llm_client


def test_secret_getter_wins_over_environment() -> None:
    settings = load_settings(
        secret_getter=lambda name: "secret-value" if name == "ANTHROPIC_API_KEY" else None,
        env={"ANTHROPIC_API_KEY": "environment-value", "LLM_PROVIDER": "anthropic"},
    )
    assert settings.anthropic_api_key == "secret-value"
    assert settings.llm_provider == "anthropic"
    assert settings.llm_model == "claude-haiku-4-5"


def test_settings_redact_keys() -> None:
    settings = load_settings(
        secret_getter=lambda name: {
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "OPENAI_API_KEY": "sk-openai-secret",
        }.get(name),
        env={"LLM_PROVIDER": "anthropic"},
    )
    rendered = repr(settings)
    assert "sk-ant-secret" not in rendered
    assert "sk-openai-secret" not in rendered
    assert settings.redacted()["anthropic_key_configured"] is True
    assert settings.redacted()["openai_key_configured"] is True


def test_provider_auto_detection_and_model_defaults() -> None:
    openai_settings = load_settings(secret_getter=lambda name: None, env={"OPENAI_API_KEY": "key"})
    assert openai_settings.llm_provider == "openai"
    assert openai_settings.llm_model == "gpt-4o-mini"
    explicit = load_settings(
        secret_getter=lambda name: None,
        env={"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "key", "LLM_MODEL": "custom-model"},
    )
    assert explicit.llm_model == "custom-model"


def test_limit_values_are_clamped(settings) -> None:
    assert settings.daily_question_cap == 25
    assert settings.session_question_cap == 10
    loaded = load_settings(
        secret_getter=lambda name: None,
        env={"DAILY_QUESTION_CAP": "999999", "MAX_TOKENS": "5", "TOP_K": "100"},
    )
    assert loaded.daily_question_cap == 10000
    assert loaded.max_tokens == 100
    assert loaded.top_k == 10


def test_factory_requires_keys_and_supports_mock(settings) -> None:
    with pytest.raises(LLMConfigurationError):
        get_llm_client(replace(settings, llm_provider="anthropic", anthropic_api_key=None))
    with pytest.raises(LLMConfigurationError):
        get_llm_client(replace(settings, llm_provider="openai", openai_api_key=None))
    with pytest.raises(LLMConfigurationError):
        get_llm_client(replace(settings, llm_provider="unknown"))
    mock = get_llm_client(replace(settings, llm_provider="mock"))
    assert isinstance(mock, MockLLMClient)
    assert mock.chat([]).text == "I don't know."
