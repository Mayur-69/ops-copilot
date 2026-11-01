from __future__ import annotations

import json
from pathlib import Path

from eval.run_eval import _grade
from src.agent import AgentResult

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TOOLS = {"search_documents", "get_sales_summary", "get_low_stock_items", "run_sql_query"}


def _questions() -> list[dict]:
    return json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))["questions"]


def test_eval_question_set_is_valid() -> None:
    questions = _questions()
    assert len(questions) == 40
    assert len({question["id"] for question in questions}) == 40
    doc_names = {path.name for path in (ROOT / "data" / "docs").glob("*.md")}
    for question in questions:
        assert question["category"]
        assert question["question"]
        assert set(question.get("expected_tools", [])) <= ALLOWED_TOOLS
        assert set(question.get("expected_sources", [])) <= doc_names
        if question.get("require_citation"):
            assert question.get("expected_sources")


def test_grade_passes_cited_document_answer() -> None:
    question = {
        "expected_tools": ["search_documents"],
        "expected_sources": ["warranty-policy.md"],
        "require_citation": True,
        "keywords_all": ["24 months"],
    }
    result = AgentResult(
        answer="The residential warranty is 24 months [warranty-policy.md - Warranty Periods].",
        tool_trace=[{"name": "search_documents", "ok": True}],
        sources=[{"source": "warranty-policy.md", "section": "Warranty Periods", "score": 0.9, "text": "24 months"}],
    )
    grades = _grade(question, result)
    assert grades["passed"] is True
    assert grades["citation_ok"] is True


def test_grade_fails_missing_citation_and_wrong_tool() -> None:
    question = {
        "expected_tools": ["get_sales_summary"],
        "expected_sources": [],
        "keywords_all": ["5,949,333"],
    }
    result = AgentResult(
        answer="Revenue was 5,949,333.83.",
        tool_trace=[{"name": "run_sql_query", "ok": True}],
    )
    grades = _grade(question, result)
    assert grades["passed"] is False
    assert grades["tool_ok"] is False


def test_grade_refusal_and_non_refusal_detection() -> None:
    refusal = _grade({"expect_refusal": True}, AgentResult(answer="I don't know."))
    assert refusal["passed"] is True
    non_refusal = _grade(
        {"expected_tools": ["search_documents"], "keywords_all": ["cannot"]},
        AgentResult(
            answer="Opened filters cannot be returned.",
            tool_trace=[{"name": "search_documents", "ok": True}],
        ),
    )
    assert non_refusal["refusal_ok"] is True
    assert non_refusal["passed"] is True
