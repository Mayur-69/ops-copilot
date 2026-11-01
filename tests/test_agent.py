from __future__ import annotations

from dataclasses import replace

import pytest

from src.agent import Agent, AgentInputError
from src.llm import LLMResponse, MockLLMClient, ToolCall


def _agent(registry, settings, responses):
    llm = MockLLMClient(responses)
    return Agent(llm, registry, settings), llm


def test_agent_calls_document_tool_and_returns_sources(registry, settings) -> None:
    agent, llm = _agent(
        registry,
        settings,
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall("call-1", "search_documents", {"query": "residential warranty", "top_k": 2})],
            ),
            LLMResponse(
                text="The residential warranty is 24 months [warranty-policy.md - Warranty Period].",
            ),
        ],
    )
    result = agent.run("How long is the residential warranty?")
    assert result.answer.startswith("The residential warranty")
    assert result.tool_trace[0]["name"] == "search_documents"
    assert result.sources[0]["source"] == "warranty-policy.md"
    assert result.citation_warnings == []
    assert len(llm.calls) == 2


def test_agent_calls_data_tool_and_marks_data_usage(registry, settings) -> None:
    agent, _ = _agent(
        registry,
        settings,
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall("call-1", "get_sales_summary", {"period": "last_30_days"})],
            ),
            LLMResponse(text="Revenue in the last 30 days was 100."),
        ],
    )
    result = agent.run("What was revenue in the last 30 days?")
    assert result.used_data_tools is True
    assert result.sources == []
    assert result.tool_trace[0]["name"] == "get_sales_summary"
    assert result.citation_warnings == []


def test_agent_normalises_unknown_answer(registry, settings) -> None:
    agent, _ = _agent(
        registry,
        settings,
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall("call-1", "search_documents", {"query": "CEO home address"})],
            ),
            LLMResponse(text="I don't know"),
        ],
    )
    result = agent.run("What is the CEO's home address?")
    assert result.answer == "I don't know."
    assert result.citation_warnings == []


def test_agent_warns_when_no_tool_was_used(registry, settings) -> None:
    agent, _ = _agent(registry, settings, [LLMResponse(text="Revenue was 100.")])
    result = agent.run("What was revenue?")
    assert "without calling a tool" in result.citation_warnings[0]


def test_agent_warns_about_unretrieved_citation(registry, settings) -> None:
    agent, _ = _agent(
        registry,
        settings,
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall("call-1", "search_documents", {"query": "warranty"})],
            ),
            LLMResponse(text="The warranty is 24 months [missing-policy.md - Unknown]."),
        ],
    )
    result = agent.run("What is the warranty?")
    assert any("not retrieved" in warning for warning in result.citation_warnings)


def test_agent_handles_tool_errors(registry, settings) -> None:
    agent, _ = _agent(
        registry,
        settings,
        [
            LLMResponse(text="", tool_calls=[ToolCall("call-1", "no_such_tool", {})]),
            LLMResponse(text="I don't know."),
        ],
    )
    result = agent.run("Can you do something impossible?")
    assert result.tool_trace[0]["ok"] is False
    assert result.answer == "I don't know."


def test_agent_enforces_tool_iteration_limit(registry, settings) -> None:
    limited = replace(settings, max_tool_iterations=1)
    agent, _ = _agent(
        registry,
        limited,
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall("call-1", "search_documents", {"query": "warranty"})],
            ),
            LLMResponse(text="The warranty is 24 months [warranty-policy.md - Warranty Period]."),
        ],
    )
    result = agent.run("What is the warranty?")
    assert "tool-call limit" in result.citation_warnings[-1]


def test_agent_rejects_empty_and_long_questions(registry, settings) -> None:
    agent, _ = _agent(registry, settings, [])
    with pytest.raises(AgentInputError):
        agent.run("   ")
    limited = replace(settings, max_input_chars=10)
    agent, _ = _agent(registry, limited, [])
    with pytest.raises(AgentInputError):
        agent.run("This question is definitely too long")
