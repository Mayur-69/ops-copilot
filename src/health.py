from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import Settings, load_settings
from src.db import read_meta
from src.rag import RagStore


@dataclass
class HealthReport:
    ok: bool
    data_as_of: str
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "data_as_of": self.data_as_of, "checks": self.checks}


def check_health(settings: Settings, *, rag: RagStore | None = None) -> HealthReport:
    checks: dict[str, dict[str, Any]] = {}

    database = Path(settings.database_path)
    database_ok = database.exists() and database.is_file()
    meta: dict[str, str] = {}
    if database_ok:
        try:
            meta = read_meta(database)
        except Exception as exc:
            database_ok = False
            checks["database_error"] = {"ok": False, "detail": str(exc)[:300]}
    checks["database"] = {
        "ok": database_ok,
        "path": str(database),
        "size_bytes": database.stat().st_size if database_ok else 0,
    }

    docs = sorted(Path(settings.docs_dir).glob("*.md")) if Path(settings.docs_dir).exists() else []
    checks["documents"] = {
        "ok": bool(docs),
        "count": len(docs),
        "path": str(settings.docs_dir),
    }

    index_ok = False
    chunk_count = 0
    if rag is not None:
        try:
            chunk_count = rag.count()
            index_ok = chunk_count > 0
        except Exception as exc:
            checks["index_error"] = {"ok": False, "detail": str(exc)[:300]}
    checks["index"] = {
        "ok": index_ok,
        "chunks": chunk_count,
        "path": str(settings.index_dir),
    }

    key_configured = bool(
        settings.anthropic_api_key if settings.llm_provider == "anthropic" else settings.openai_api_key
    )
    if settings.llm_provider == "mock":
        key_configured = True
    checks["llm"] = {
        "ok": key_configured,
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "key_configured": key_configured,
    }

    required = ["database", "documents", "index", "llm"]
    ok = all(checks[name]["ok"] for name in required if name in checks)
    return HealthReport(ok=ok, data_as_of=meta.get("data_as_of", ""), checks=checks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Ops Copilot runtime health.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    settings = load_settings()
    rag = None
    try:
        from src.bootstrap import ensure_index
        from src.embeddings import FastEmbedder

        result = ensure_index(
            settings,
            embedder=FastEmbedder(
                model_name=settings.fastembed_model,
                cache_dir=settings.fastembed_cache,
            ),
        )
        rag = result.rag
    except Exception:
        pass
    report = check_health(settings, rag=rag)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status = "OK" if report.ok else "FAILED"
        print(f"Ops Copilot health: {status}")
        print(f"Data as of: {report.data_as_of or 'unknown'}")
        for name, check in report.checks.items():
            mark = "ok" if check.get("ok") else "FAIL"
            detail = ", ".join(f"{key}={value}" for key, value in check.items() if key != "ok")
            print(f"  [{mark}] {name}: {detail}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
