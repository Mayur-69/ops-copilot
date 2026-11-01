# Ops Copilot

Ops Copilot is a private AI operations assistant for **AquaPure Water Solutions**, a fictional water-purifier company. Staff can ask policy questions, look up sales and inventory, and run read-only data analysis from one chat interface.

The project is intentionally self-contained: a deterministic SQLite database, a small company document set, a local Chroma vector index, a Streamlit UI, an MCP server, tests, and an evaluation suite.

## What it does

- Answers policy, warranty, returns, shipping, installation, filter, escalation, dealer, and product-manual questions from company documents.
- Answers sales, order, inventory, ticket, customer, and product questions from the read-only SQLite database.
- Uses four tools: `search_documents`, `get_sales_summary`, `get_low_stock_items`, and `run_sql_query`.
- Shows retrieved sources, tool activity, token usage, and citation warnings in the UI.
- Refuses to invent answers when the evidence is missing and returns `I don't know.`
- Enforces session and daily question limits, read-only SQL, row limits, SQL timeouts, and input-size limits.
- Exposes the same tools to MCP clients through `mcp_server.py`.

## Architecture

```text
Browser
  |
  v
Streamlit app (streamlit_app.py)
  |
  v
Agent loop (src/agent.py) ---> LLM provider (src/llm.py)
  |                              Anthropic / OpenAI / mock
  v
Tool registry (src/tools.py)
  |-- search_documents ----> Chroma index (data/index/chroma)
  |                            ^
  |                            |
  |                         fastembed + data/docs/*.md
  |
  |-- get_sales_summary ----> read-only SQLite (data/ops_copilot.db)
  |-- get_low_stock_items --> read-only SQLite
  |-- run_sql_query --------> validated read-only SQLite

MCP clients ---> mcp_server.py ---> the same tool registry
```

The index is built automatically on first app start from `data/docs/*.md`. It is not committed; the source documents and the SQLite database are.

### Request flow

1. The user asks a question in the Streamlit chat.
2. The agent sends the question, database schema, and tool definitions to the selected model.
3. The model chooses tools. Tool results are returned as JSON.
4. The agent loops until the model produces a final answer or reaches the tool-call limit.
5. The UI displays the answer, retrieved document sources, tool trace, and warnings.

### Data as-of date

All relative periods use `meta.data_as_of` (`2026-11-01`), never the wall clock. For example, "last 30 days" means `2026-10-03` through `2026-11-01`. Revenue is `SUM(orders.total)` for orders with status `completed` or `shipped`.

## Quick start

### 1. Create the environment

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

macOS/Linux:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configure secrets

Copy the example and replace the placeholder:

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
```

```toml
LLM_PROVIDER = "anthropic"
LLM_MODEL = "claude-haiku-4-5"
ANTHROPIC_API_KEY = "your-real-key"
DAILY_QUESTION_CAP = 200
```

`.streamlit/secrets.toml` is gitignored. Environment variables work too; `load_settings` checks `.streamlit/secrets.toml` first, then the environment. Never commit a real key.

For an OpenAI-backed setup, set `LLM_PROVIDER="openai"`, `LLM_MODEL="gpt-4o-mini"`, and `OPENAI_API_KEY`. To preview the UI without a key, set `LLM_PROVIDER="mock"`; answers will be placeholders.

### 3. Run the app

```powershell
streamlit run streamlit_app.py
```

Open the URL Streamlit prints, normally `http://localhost:8501`. The first run downloads the fastembed model and builds the Chroma index. Later runs reuse `data/index/chroma` and `data/.fastembed_cache`.

### 4. Rebuild or inspect

The app rebuilds the index automatically when the document fingerprint changes. To force a rebuild:

```powershell
Remove-Item -Recurse -Force data\index
streamlit run streamlit_app.py
```

Health check:

```powershell
python -m src.health --json
```

Regenerate the deterministic database:

```powershell
python scripts/generate_data.py --out-dir data --force
```

The generator uses seed `42` and as-of `2026-11-01` by default. The committed database has 40 products, 1,500 customers, 5,000 orders, 7,462 order items, 120 inventory rows, and 900 tickets.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | auto-detect, then `anthropic` | `anthropic`, `openai`, or `mock` |
| `LLM_MODEL` | `claude-haiku-4-5` / `gpt-4o-mini` | Provider model name |
| `ANTHROPIC_API_KEY` | none | Anthropic key |
| `OPENAI_API_KEY` | none | OpenAI key |
| `DAILY_QUESTION_CAP` | `200` | App-wide daily question limit |
| `SESSION_QUESTION_CAP` | `10` | Per-browser-session question limit |
| `MAX_TOKENS` | `800` | Model output limit |
| `MAX_TOOL_ITERATIONS` | `6` | Maximum tool-call rounds |
| `MAX_INPUT_CHARS` | `2000` | Maximum question length |
| `TOP_K` | `5` | Documents retrieved per search |
| `MIN_SCORE` | `0.0` | Minimum similarity score |
| `SQL_ROW_LIMIT` | `200` | Maximum rows returned by a SQL tool |
| `SQL_TIMEOUT_SECONDS` | `5.0` | SQLite query timeout |
| `MAX_SESSION_UPLOADS` | `5` | Uploaded files per session |
| `OPS_DATA_DIR` | `data` | Database and generated data directory |
| `OPS_DOCS_DIR` | `data/docs` | Markdown document directory |
| `OPS_INDEX_DIR` | `data/index/chroma` | Chroma persistence directory |
| `OPS_USAGE_DB` | `data/usage.db` | Daily question counter |
| `FASTEMBED_CACHE_PATH` | `data/.fastembed_cache` | Embedding model cache |

## Tools

| Tool | Inputs | Returns |
| --- | --- | --- |
| `search_documents` | `query`, `top_k` | Ranked chunks with source, section, score, and text |
| `get_sales_summary` | `period` (`last_7_days`, `last_30_days`, `last_90_days`, `last_12_months`, `this_month`, `last_month`, `ytd`, `all_time`, or `YYYY-MM`) | Revenue, orders, units, AOV, top products, monthly trend |
| `get_low_stock_items` | optional `threshold`, `limit` | Products at or below reorder point, shortfall, suggested reorder quantity |
| `run_sql_query` | `sql` | Columns, rows, truncation flag, and the validated SQL |

SQL rules:

- Only one `SELECT` or `WITH ... SELECT` statement.
- Write, DDL, `PRAGMA`, `ATTACH`, `sqlite_master`, and file/extension functions are rejected.
- Queries are wrapped with a row limit and run on a read-only SQLite connection with a timeout.
- The model receives the schema and must use `meta.data_as_of` for relative dates.

## MCP server

`mcp_server.py` exposes the same four read-only tools over stdio using MCP 2.x (`mcp.server.mcpserver.MCPServer`). It does not need an LLM key.

```powershell
python mcp_server.py
```

Example MCP client configuration (replace the absolute paths):

```json
{
  "mcpServers": {
    "ops-copilot": {
      "command": "<repo>\\.venv\\Scripts\\python.exe",
      "args": ["<repo>\\mcp_server.py"],
      "env": {
        "OPS_DATA_DIR": "<repo>\\data"
      }
    }
  }
}
```

The server builds the local index on first use, then serves:

- `search_documents`
- `get_sales_summary`
- `get_low_stock_items`
- `run_sql_query`

## Evaluation

The eval suite has 40 questions across warranty, returns, shipping, installation, filters, escalation, dealer operations, FAQ, water quality, manuals, sales data, inventory, custom SQL, combined tool use, and refusal behavior.

```powershell
python eval/run_eval.py
```

This writes `eval/results.json` and `eval/results.md`. The runner grades tool choice, retrieved sources, required citations, expected keywords, refusal behavior, and citation warnings. A run requires a real model key and makes model API calls.

Useful options:

```powershell
python eval/run_eval.py --limit 5 --provider mock
python eval/run_eval.py --questions eval/questions.json --output eval/results.json --markdown eval/results.md
```

## Tests and linting

```powershell
pip install -r requirements-dev.txt
python -m pytest
ruff check src scripts tests eval mcp_server.py streamlit_app.py
```

The test suite covers data generation, chunking, retrieval, SQL validation, tools, LLM factory behavior, agent tool loops, bootstrap/index rebuilds, uploads, usage limits, health checks, and MCP tool registration.

Streamlit app smoke test:

```powershell
python -c "from streamlit.testing.v1 import AppTest; at = AppTest.from_file('streamlit_app.py', default_timeout=120).run(); print(len(at.exception), len(at.chat_input))"
```

## Project layout

```text
.
|-- streamlit_app.py          Streamlit UI
|-- mcp_server.py             MCP stdio server
|-- Dockerfile
|-- DEPLOY.md
|-- data/
|   |-- ops_copilot.db        Committed synthetic SQLite database
|   |-- meta.json
|   |-- docs/*.md             13 committed source documents
|   |-- index/                Generated Chroma index (gitignored)
|   |-- .fastembed_cache/     Generated model cache (gitignored)
|   `-- usage.db              Generated daily counter (gitignored)
|-- src/
|   |-- agent.py              Tool-calling loop and citation checks
|   |-- bootstrap.py          Index build/rebuild logic
|   |-- chunking.py           Markdown-aware chunking
|   |-- config.py             Settings and secrets
|   |-- db.py                 Schema and read-only SQLite access
|   |-- embeddings.py         fastembed and deterministic test embedder
|   |-- health.py             Runtime health check
|   |-- llm.py                Anthropic/OpenAI/mock clients
|   |-- periods.py            Relative period resolution
|   |-- rag.py                Chroma store and result merging
|   |-- sql_validator.py      Read-only SQL validation
|   |-- tools.py              Tool implementations
|   |-- uploads.py            Session document uploads
|   `-- usage.py              Daily question limits
|-- scripts/generate_data.py  Deterministic data generator
|-- tests/                    Pytest suite
`-- eval/                     Questions and evaluation runner
```

## Security and limits

- The database is synthetic. No real customer, employee, or company data is present.
- The app never exposes API keys in the UI, logs, or repository.
- SQL is read-only and validated; write and DDL statements are rejected.
- Tool results are size-limited and passed to the model as data, not instructions.
- Session uploads are ephemeral and are not written to the shared knowledge base.
- The daily question counter is best-effort. Streamlit Community Cloud can reset local files when an app restarts.
- The model can still make mistakes. Staff should verify high-impact answers against the cited source.

## Deployment

See [DEPLOY.md](DEPLOY.md) for GitHub, Streamlit Community Cloud, Docker, MCP, and post-deployment verification steps.
