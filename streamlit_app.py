from __future__ import annotations

from uuid import uuid4

import streamlit as st

from src.agent import Agent, AgentInputError
from src.bootstrap import IndexBuildResult, ensure_index
from src.config import LLMConfigurationError, Settings, load_settings
from src.llm import LLMError, MockLLMClient, get_llm_client
from src.rag import RagStore
from src.tools import ToolRegistry
from src.uploads import UploadError, add_uploads
from src.usage import UsageLimitError, UsageTracker

EXAMPLES = [
    "What is the warranty period for a residential RO purifier?",
    "Which products are at or below their reorder point?",
    "Show revenue and the top products for the last 30 days.",
    "What is the return window and who pays return shipping?",
    "How do I troubleshoot low water flow?",
]

st.set_page_config(
    page_title="Ops Copilot | AquaPure",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _secret_getter(name: str):
    try:
        return st.secrets[name]
    except Exception:
        return None


@st.cache_resource(show_spinner=False)
def _settings() -> Settings:
    return load_settings(secret_getter=_secret_getter)


@st.cache_resource(show_spinner=False)
def _base_runtime() -> tuple[Settings, RagStore, IndexBuildResult]:
    settings = _settings()
    result = ensure_index(settings)
    return settings, result.rag, result


@st.cache_resource(show_spinner=False)
def _llm_runtime() -> tuple[object, bool, str | None]:
    settings = _settings()
    try:
        return get_llm_client(settings), False, None
    except LLMConfigurationError as exc:
        return MockLLMClient(), True, str(exc)


@st.cache_resource(show_spinner=False)
def _usage_tracker(path: str) -> UsageTracker:
    return UsageTracker(path)


def _session_rag(base_rag: RagStore) -> RagStore:
    if "session_rag" not in st.session_state:
        st.session_state.session_rag = RagStore.ephemeral(
            base_rag.embedder,
            collection_name=f"session_{uuid4().hex[:10]}",
        )
    return st.session_state.session_rag


def _ensure_session(settings: Settings, base_rag: RagStore, llm: object) -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "questions_asked" not in st.session_state:
        st.session_state.questions_asked = 0
    if "upload_sources" not in st.session_state:
        st.session_state.upload_sources = set()
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None
    session_rag = _session_rag(base_rag)
    if "registry" not in st.session_state:
        st.session_state.registry = ToolRegistry(
            settings.database_path,
            base_rag,
            settings,
            session_rag=session_rag,
        )
    if "agent" not in st.session_state:
        st.session_state.agent = Agent(llm, st.session_state.registry, settings)


def _render_sources(message: dict) -> None:
    sources = message.get("sources") or []
    if not sources:
        return
    with st.expander(f"Sources ({len(sources)})", expanded=False):
        for source in sources:
            uploaded = " · uploaded" if source.get("uploaded") else ""
            st.markdown(f"**{source.get('source', '')} — {source.get('section', '')}**")
            st.caption(f"similarity {source.get('score', 0.0):.3f}{uploaded}")
            text = str(source.get("text", ""))
            st.write(text[:700] + ("..." if len(text) > 700 else ""))


def _render_trace(message: dict) -> None:
    trace = message.get("trace") or []
    if not trace:
        return
    with st.expander("Tool activity", expanded=False):
        for item in trace:
            state = "ok" if item.get("ok") else "error"
            st.markdown(f"`{item.get('name', 'tool')}` · {state} · {item.get('duration_ms', 0)} ms")
            if item.get("error"):
                st.caption(str(item["error"])[:500])
            elif item.get("name") == "run_sql_query" and item.get("result"):
                st.code(str(item["result"].get("sql", "")), language="sql")
                st.caption(f"{item['result'].get('row_count', 0)} row(s) returned")


def _render_message(message: dict) -> None:
    with st.chat_message(message.get("role", "assistant")):
        st.markdown(message.get("content", ""))
        for warning in message.get("warnings") or []:
            st.warning(warning)
        _render_sources(message)
        _render_trace(message)
        if message.get("meta"):
            st.caption(message["meta"])


def _ask(prompt: str, settings: Settings, usage: UsageTracker) -> None:
    prompt = prompt.strip()
    if not prompt:
        return
    if len(prompt) > settings.max_input_chars:
        st.error(f"Please keep questions under {settings.max_input_chars} characters.")
        return
    if st.session_state.questions_asked >= settings.session_question_cap:
        st.error(
            f"This session has reached its {settings.session_question_cap}-question limit. "
            "Start a new conversation to continue."
        )
        return
    try:
        usage.check_and_increment(settings.daily_question_cap)
    except UsageLimitError as exc:
        st.error(str(exc))
        return

    history = [
        (message["role"], message["content"])
        for message in st.session_state.messages
        if message.get("role") in {"user", "assistant"}
    ]
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.questions_asked += 1

    try:
        with st.spinner("Checking documents and data..."):
            result = st.session_state.agent.run(prompt, history=history)
        meta = f"{result.provider} · {result.model} · {result.input_tokens + result.output_tokens} tokens"
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result.answer,
                "sources": result.sources,
                "trace": result.tool_trace,
                "warnings": result.citation_warnings,
                "meta": meta,
            }
        )
    except (AgentInputError, LLMError) as exc:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "I couldn't complete that request. Please try again.",
                "warnings": [str(exc)[:500]],
            }
        )
    except Exception as exc:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "I couldn't complete that request because the assistant hit an unexpected error.",
                "warnings": [str(exc)[:500]],
            }
        )
    st.rerun()


def _sidebar(
    settings: Settings,
    index: IndexBuildResult,
    usage: UsageTracker,
    demo_mode: bool,
    demo_reason: str | None,
) -> None:
    with st.sidebar:
        st.title("Ops Copilot")
        st.caption("Private assistant for AquaPure Water Solutions")
        st.divider()
        st.markdown(f"**Data as of:** {st.session_state.registry.data_as_of}")
        st.markdown(f"**Indexed chunks:** {index.chunk_count:,}")
        st.markdown(f"**Provider:** `{settings.llm_provider}` · `{settings.llm_model}`")
        if demo_mode:
            st.warning(
                "Demo mode: no model API key is configured, so answers are placeholders. "
                "Add a key to `.streamlit/secrets.toml` to enable the real assistant."
            )
            if demo_reason:
                st.caption(demo_reason)
        else:
            st.success("Model configured")

        st.divider()
        st.subheader("Try a question")
        for example in EXAMPLES:
            if st.button(example, use_container_width=True):
                st.session_state.pending_question = example

        st.divider()
        st.subheader("Session documents")
        uploaded = st.file_uploader(
            "Add policies, manuals, or notes",
            type=["md", "txt", "pdf"],
            accept_multiple_files=True,
            help="Uploaded documents are available only in this browser session. Max 5 files, 5 MB each.",
        )
        if st.button("Add uploaded documents", use_container_width=True):
            try:
                documents = add_uploads(
                    st.session_state.session_rag,
                    uploaded or [],
                    max_files=settings.max_session_uploads,
                    existing_sources=st.session_state.upload_sources,
                )
                st.session_state.upload_sources.update(item.source for item in documents)
                st.success(f"Added {len(documents)} document(s) to this session.")
            except UploadError as exc:
                st.error(str(exc))
        if st.session_state.upload_sources:
            st.caption("In session: " + ", ".join(sorted(st.session_state.upload_sources)))
            if st.button("Clear uploaded documents", use_container_width=True):
                st.session_state.session_rag.reset()
                st.session_state.upload_sources = set()
                st.success("Session documents cleared.")
        st.caption(f"Session questions: {st.session_state.questions_asked}/{settings.session_question_cap}")
        st.caption(f"Today's questions: {usage.daily_count()}/{settings.daily_question_cap}")

        st.divider()
        if st.button("Reset conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.questions_asked = 0
            st.rerun()
        with st.expander("How it works"):
            st.write(
                "Ops Copilot searches company documents and queries the read-only operations "
                "database. It only answers from retrieved evidence and shows its sources. "
                "If it cannot find an answer, it says: I don't know."
            )
        with st.expander("Guardrails"):
            st.write(
                f"- {settings.session_question_cap} questions per session\n"
                f"- {settings.daily_question_cap} questions per day across the app\n"
                "- Read-only SQL only; write and DDL statements are rejected\n"
                "- No access to secrets, customer PII, or external websites\n"
                "- Session uploads are not saved to the shared knowledge base"
            )
        st.caption("Synthetic company, documents, and data. Not a real business.")


def main() -> None:
    try:
        settings, base_rag, index = _base_runtime()
    except Exception as exc:
        st.error(f"Could not start Ops Copilot: {exc}")
        st.stop()
    llm, demo_mode, demo_reason = _llm_runtime()
    usage = _usage_tracker(str(settings.usage_db))
    _ensure_session(settings, base_rag, llm)

    _sidebar(settings, index, usage, demo_mode, demo_reason)

    st.title("Operations Copilot")
    st.caption(
        "Ask about policies, warranties, returns, inventory, sales, or support tickets. "
        "Answers are grounded in company documents and the operations database."
    )

    if not st.session_state.messages:
        st.info(
            "Start with a question below, or choose an example in the sidebar. "
            "Every answer shows the tool calls and document sources behind it."
        )

    for message in st.session_state.messages:
        _render_message(message)

    prompt = st.chat_input("Ask Ops Copilot a question...")
    if st.session_state.pending_question:
        prompt = st.session_state.pending_question
        st.session_state.pending_question = None
    if prompt:
        _ask(prompt, settings, usage)


main()
