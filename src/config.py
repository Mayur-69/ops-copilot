from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class LLMConfigurationError(RuntimeError):
    pass


def _read_secrets_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def default_secret_getter(name: str) -> Any:
    secrets = _read_secrets_file(ROOT / ".streamlit" / "secrets.toml")
    if name in secrets:
        return secrets[name]
    return os.environ.get(name)


def _as_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _as_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    llm_model: str
    anthropic_api_key: str | None = field(default=None, repr=False)
    openai_api_key: str | None = field(default=None, repr=False)
    data_dir: Path = DEFAULT_DATA_DIR
    docs_dir: Path = DEFAULT_DATA_DIR / "docs"
    index_dir: Path = DEFAULT_DATA_DIR / "index" / "chroma"
    usage_db: Path = DEFAULT_DATA_DIR / "usage.db"
    fastembed_cache: Path = DEFAULT_DATA_DIR / ".fastembed_cache"
    fastembed_model: str = "BAAI/bge-small-en-v1.5"
    daily_question_cap: int = 200
    session_question_cap: int = 10
    max_tokens: int = 800
    max_tool_iterations: int = 6
    max_input_chars: int = 2000
    top_k: int = 5
    min_score: float = 0.0
    sql_row_limit: int = 200
    sql_timeout_seconds: float = 5.0
    max_session_uploads: int = 5

    @property
    def database_path(self) -> Path:
        return self.data_dir / "ops_copilot.db"

    def redacted(self) -> dict[str, Any]:
        return {
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "anthropic_key_configured": bool(self.anthropic_api_key),
            "openai_key_configured": bool(self.openai_api_key),
            "data_dir": str(self.data_dir),
            "daily_question_cap": self.daily_question_cap,
            "session_question_cap": self.session_question_cap,
        }


def load_settings(
    secret_getter: Callable[[str], Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        pass

    environment = env if env is not None else os.environ
    getter = secret_getter or default_secret_getter

    def get(name: str, default: str | None = None) -> Any:
        value = getter(name)
        if value is None:
            value = environment.get(name)
        return default if value is None else value

    provider = str(get("LLM_PROVIDER", "") or "").strip().lower()
    anthropic_key = get("ANTHROPIC_API_KEY")
    openai_key = get("OPENAI_API_KEY")
    if not provider:
        if anthropic_key:
            provider = "anthropic"
        elif openai_key:
            provider = "openai"
        else:
            provider = "anthropic"
    default_model = DEFAULT_OPENAI_MODEL if provider == "openai" else DEFAULT_ANTHROPIC_MODEL
    model = str(get("LLM_MODEL", default_model) or default_model).strip()

    data_dir = Path(str(get("OPS_DATA_DIR", str(DEFAULT_DATA_DIR)))).expanduser()
    docs_dir = Path(str(get("OPS_DOCS_DIR", str(data_dir / "docs")))).expanduser()
    index_dir = Path(str(get("OPS_INDEX_DIR", str(data_dir / "index" / "chroma")))).expanduser()
    usage_db = Path(str(get("OPS_USAGE_DB", str(data_dir / "usage.db")))).expanduser()
    fastembed_cache = Path(str(get("FASTEMBED_CACHE_PATH", str(data_dir / ".fastembed_cache")))).expanduser()

    return Settings(
        llm_provider=provider,
        llm_model=model,
        anthropic_api_key=str(anthropic_key) if anthropic_key else None,
        openai_api_key=str(openai_key) if openai_key else None,
        data_dir=data_dir,
        docs_dir=docs_dir,
        index_dir=index_dir,
        usage_db=usage_db,
        fastembed_cache=fastembed_cache,
        fastembed_model=str(get("FASTEMBED_MODEL", "BAAI/bge-small-en-v1.5")),
        daily_question_cap=_as_int(get("DAILY_QUESTION_CAP", 200), 200, minimum=1, maximum=10000),
        session_question_cap=_as_int(get("SESSION_QUESTION_CAP", 10), 10, minimum=1, maximum=100),
        max_tokens=_as_int(get("MAX_TOKENS", 800), 800, minimum=100, maximum=2000),
        max_tool_iterations=_as_int(get("MAX_TOOL_ITERATIONS", 6), 6, minimum=1, maximum=12),
        max_input_chars=_as_int(get("MAX_INPUT_CHARS", 2000), 2000, minimum=100, maximum=8000),
        top_k=_as_int(get("TOP_K", 5), 5, minimum=1, maximum=10),
        min_score=_as_float(get("MIN_SCORE", 0.0), 0.0, minimum=0.0, maximum=0.99),
        sql_row_limit=_as_int(get("SQL_ROW_LIMIT", 200), 200, minimum=1, maximum=1000),
        sql_timeout_seconds=_as_float(get("SQL_TIMEOUT_SECONDS", 5.0), 5.0, minimum=0.5, maximum=30.0),
        max_session_uploads=_as_int(get("MAX_SESSION_UPLOADS", 5), 5, minimum=1, maximum=20),
    )
