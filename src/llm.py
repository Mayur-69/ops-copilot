from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from src.config import LLMConfigurationError, Settings


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(ABC):
    provider: str
    model: str

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 800,
        temperature: float = 0.0,
    ) -> LLMResponse:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str, timeout: float = 60.0) -> None:
        if not api_key:
            raise LLMConfigurationError("ANTHROPIC_API_KEY is not configured.")
        import anthropic

        self.provider = "anthropic"
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)

    def _convert_messages(self, messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
        system_parts = [message.content for message in messages if message.role == "system" and message.content]
        system = "\n\n".join(system_parts)
        converted: list[dict[str, Any]] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role == "system":
                index += 1
                continue
            if message.role == "tool":
                blocks: list[dict[str, Any]] = []
                while index < len(messages) and messages[index].role == "tool":
                    tool_message = messages[index]
                    blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_message.tool_call_id or "",
                            "content": tool_message.content,
                        }
                    )
                    index += 1
                converted.append({"role": "user", "content": blocks})
                continue
            if message.role == "assistant":
                blocks = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for call in message.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": call.arguments,
                        }
                    )
                if blocks:
                    converted.append({"role": "assistant", "content": blocks})
                index += 1
                continue
            converted.append({"role": "user", "content": message.content})
            index += 1
        return system, converted

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 800,
        temperature: float = 0.0,
    ) -> LLMResponse:
        system, converted = self._convert_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": converted,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool["input_schema"],
                }
                for tool in tools
            ]
        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:
            raise LLMError(f"Anthropic request failed: {str(exc)[:300]}") from None
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in response.content:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                text_parts.append(str(getattr(block, "text", "")))
            elif block_type == "tool_use":
                calls.append(
                    ToolCall(
                        id=str(getattr(block, "id", "")),
                        name=str(getattr(block, "name", "")),
                        arguments=dict(getattr(block, "input", {}) or {}),
                    )
                )
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text="".join(text_parts).strip(),
            tool_calls=calls,
            stop_reason=str(getattr(response, "stop_reason", "") or ""),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str, timeout: float = 60.0) -> None:
        if not api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is not configured.")
        import openai

        self.provider = "openai"
        self.model = model
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=2)

    def _convert_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                converted.append({"role": "system", "content": message.content})
            elif message.role == "user":
                converted.append({"role": "user", "content": message.content})
            elif message.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": message.content or None}
                if message.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in message.tool_calls
                    ]
                converted.append(entry)
            elif message.role == "tool":
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id or "",
                        "content": message.content,
                    }
                )
        return converted

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 800,
        temperature: float = 0.0,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
                for tool in tools
            ]
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise LLMError(f"OpenAI request failed: {str(exc)[:300]}") from None
        choice = response.choices[0]
        message = choice.message
        calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw": call.function.arguments}
            calls.append(
                ToolCall(
                    id=str(call.id),
                    name=str(call.function.name),
                    arguments=arguments if isinstance(arguments, dict) else {"_raw": arguments},
                )
            )
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=str(message.content or "").strip(),
            tool_calls=calls,
            stop_reason=str(choice.finish_reason or ""),
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )


class MockLLMClient(LLMClient):
    def __init__(
        self,
        responses: list[LLMResponse] | None = None,
        *,
        provider: str = "mock",
        model: str = "mock-model",
    ) -> None:
        self.provider = provider
        self.model = model
        self.responses = list(responses or [])
        self.calls: list[list[ChatMessage]] = []

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 800,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(text="I don't know.", stop_reason="end_turn")


def get_llm_client(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.strip().lower()
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMConfigurationError(
                "ANTHROPIC_API_KEY is not configured. Add it to .streamlit/secrets.toml or the environment."
            )
        return AnthropicClient(settings.anthropic_api_key, settings.llm_model)
    if provider == "openai":
        if not settings.openai_api_key:
            raise LLMConfigurationError(
                "OPENAI_API_KEY is not configured. Add it to .streamlit/secrets.toml or the environment."
            )
        return OpenAIClient(settings.openai_api_key, settings.llm_model)
    if provider == "mock":
        return MockLLMClient()
    raise LLMConfigurationError(
        f"Unsupported LLM_PROVIDER '{settings.llm_provider}'. Use anthropic, openai, or mock."
    )
