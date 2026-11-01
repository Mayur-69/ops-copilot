from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent import Agent
from src.bootstrap import ensure_index
from src.config import load_settings
from src.llm import get_llm_client
from src.tools import ToolRegistry

REFUSAL_PREFIXES = (
    "i don't know",
    "i do not know",
    "i can't",
    "i cannot",
    "i won't",
    "i will not",
    "i am unable",
    "i'm unable",
    "unable to",
    "cannot",
    "can't",
    "not allowed",
    "not authorised",
    "not authorized",
)


def _is_refusal(answer: str) -> bool:
    lowered = answer.strip().casefold()
    return any(lowered.startswith(prefix) for prefix in REFUSAL_PREFIXES)


def _has_keyword(text: str, keyword: str) -> bool:
    return keyword.casefold() in text.casefold()


def _grade(question: dict[str, Any], result: Any) -> dict[str, Any]:
    answer = result.answer if result else ""
    trace = result.tool_trace if result else []
    sources = {str(item.get("source", "")) for item in (result.sources if result else [])}
    successful_tools = {str(item.get("name", "")) for item in trace if item.get("ok")}
    expected_tools = question.get("expected_tools", [])
    expected_sources = question.get("expected_sources", [])
    source_mode = question.get("source_mode", "any")

    tool_ok = all(tool in successful_tools for tool in expected_tools)
    if expected_sources:
        matched = [source for source in expected_sources if source in sources]
        source_ok = len(matched) == len(expected_sources) if source_mode == "all" else bool(matched)
    else:
        source_ok = True
    citation_ok = True
    if question.get("require_citation"):
        citation_ok = any(_has_keyword(answer, source) for source in expected_sources)

    keywords_all = question.get("keywords_all", [])
    keywords_any = question.get("keywords_any", [])
    keyword_ok = all(_has_keyword(answer, keyword) for keyword in keywords_all)
    if keywords_any:
        keyword_ok = keyword_ok and any(_has_keyword(answer, keyword) for keyword in keywords_any)

    refusal = _is_refusal(answer)
    refusal_ok = refusal if question.get("expect_refusal") else not refusal
    warning_ok = not any(
        "not retrieved" in str(warning).casefold() for warning in (result.citation_warnings if result else [])
    )
    passed = all([tool_ok, source_ok, citation_ok, keyword_ok, refusal_ok, warning_ok])
    return {
        "passed": passed,
        "tool_ok": tool_ok,
        "source_ok": source_ok,
        "citation_ok": citation_ok,
        "keyword_ok": keyword_ok,
        "refusal_ok": refusal_ok,
        "warning_ok": warning_ok,
        "successful_tools": sorted(successful_tools),
        "retrieved_sources": sorted(sources),
    }


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Ops Copilot evaluation",
        "",
        f"- Run: {report['generated_at']}",
        f"- Provider: `{report['provider']}` · model: `{report['model']}`",
        f"- Data as of: `{report['data_as_of']}`",
        f"- Overall: **{report['summary']['passed']}/{report['summary']['total']} passed** "
        f"({report['summary']['pass_rate']:.0%})",
        "",
        "## Results by category",
        "",
        "| Category | Passed | Total |",
        "| --- | ---: | ---: |",
    ]
    for category, values in sorted(report["summary"]["by_category"].items()):
        lines.append(f"| {category} | {values['passed']} | {values['total']} |")
    lines.extend(
        [
            "",
            "## Question results",
            "",
            "| ID | Pass | Tools | Sources | Refusal | Answer excerpt |",
            "| --- | :---: | --- | --- | :---: | --- |",
        ]
    )
    for item in report["results"]:
        answer = item["answer"].replace("\n", " ").replace("|", "\\|")[:240]
        tools = ", ".join(item["grades"]["successful_tools"]) or "none"
        sources = ", ".join(item["grades"]["retrieved_sources"]) or "none"
        lines.append(
            f"| {item['id']} | {'yes' if item['grades']['passed'] else 'no'} | {tools} | "
            f"{sources} | {'yes' if item['grades']['refusal_ok'] else 'no'} | {answer} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_eval(
    questions: list[dict[str, Any]],
    agent: Agent,
    *,
    sleep_seconds: float = 0.2,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        started = time.perf_counter()
        error = None
        result = None
        try:
            result = agent.run(question["question"])
        except Exception as exc:
            error = str(exc)[:500]
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        grades = _grade(question, result)
        results.append(
            {
                "id": question["id"],
                "category": question["category"],
                "question": question["question"],
                "answer": result.answer if result else "",
                "error": error,
                "grades": grades,
                "citation_warnings": result.citation_warnings if result else [],
                "latency_ms": elapsed_ms,
                "input_tokens": result.input_tokens if result else 0,
                "output_tokens": result.output_tokens if result else 0,
            }
        )
        status = "PASS" if grades["passed"] else "FAIL"
        print(f"[{index:02d}/{len(questions)}] {status} {question['id']} ({elapsed_ms} ms)", flush=True)
        if sleep_seconds:
            time.sleep(sleep_seconds)
    return results


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, dict[str, int]] = {}
    for item in results:
        category = item["category"]
        by_category.setdefault(category, {"passed": 0, "total": 0})
        by_category[category]["total"] += 1
        if item["grades"]["passed"]:
            by_category[category]["passed"] += 1
    total = len(results)
    passed = sum(1 for item in results if item["grades"]["passed"])
    return {
        "passed": passed,
        "total": total,
        "pass_rate": (passed / total) if total else 0.0,
        "by_category": dict(sorted(by_category.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Ops Copilot evaluation suite.")
    parser.add_argument("--questions", default="eval/questions.json")
    parser.add_argument("--output", default="eval/results.json")
    parser.add_argument("--markdown", default="eval/results.md")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--provider", default=None, help="Override LLM_PROVIDER, for example mock.")
    parser.add_argument("--sleep", type=float, default=0.2)
    args = parser.parse_args(argv)

    questions_path = Path(args.questions)
    payload = json.loads(questions_path.read_text(encoding="utf-8"))
    questions = payload["questions"]
    if args.limit:
        questions = questions[: args.limit]

    settings = load_settings()
    if args.provider:
        model = "mock-model" if args.provider == "mock" else settings.llm_model
        settings = replace(settings, llm_provider=args.provider, llm_model=model)
    try:
        llm = get_llm_client(settings)
    except Exception as exc:
        print(f"Could not create LLM client: {exc}", file=sys.stderr)
        return 2

    index = ensure_index(settings)
    registry = ToolRegistry(settings.database_path, index.rag, settings)
    agent = Agent(llm, registry, settings)
    print(
        f"Running {len(questions)} questions with {settings.llm_provider}/{settings.llm_model}; "
        f"data as of {registry.data_as_of}.",
        flush=True,
    )
    results = run_eval(questions, agent, sleep_seconds=args.sleep)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "data_as_of": registry.data_as_of,
        "questions_file": str(questions_path),
        "summary": _summary(results),
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_markdown(Path(args.markdown), report)
    summary = report["summary"]
    print(f"Overall: {summary['passed']}/{summary['total']} passed ({summary['pass_rate']:.0%})")
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
