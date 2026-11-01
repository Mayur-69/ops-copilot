# Deploying Ops Copilot

The supported demo deployment is Streamlit Community Cloud, with the MCP server available locally. Docker is provided for self-hosting.

## 1. Pre-flight checks

Run these from the repository root:

```powershell
python -m pytest
ruff check src scripts tests eval mcp_server.py streamlit_app.py
python -m src.health --json
```

The health check should report `"ok": true` when the database, documents, index, and model key are configured. The first health check or app start downloads the fastembed model and builds `data/index/chroma`; this can take a minute or two.

Do not commit `.streamlit/secrets.toml`, `.env`, `data/index/`, `data/.fastembed_cache/`, or `data/usage.db`.

## 2. Create the GitHub repository

The project is already a git repository. Create a public repository and push `main`:

```powershell
gh repo create Mayur-69/ops-copilot --public --source=. --remote=origin --push
```

If the remote already exists:

```powershell
git remote add origin https://github.com/Mayur-69/ops-copilot.git
git push -u origin main
```

Verify that `data/ops_copilot.db` and `data/docs/` are present in the repository, and that secrets and generated indexes are absent.

## 3. Deploy on Streamlit Community Cloud

1. Sign in at <https://share.streamlit.io> with the GitHub account that owns the repository.
2. Choose **New app**.
3. Select repository `Mayur-69/ops-copilot`, branch `main`, and main file `streamlit_app.py`.
4. Open **Advanced settings** and select Python **3.11**.
5. In **Secrets**, paste:

```toml
LLM_PROVIDER = "anthropic"
LLM_MODEL = "claude-haiku-4-5"
ANTHROPIC_API_KEY = "your-real-key"
DAILY_QUESTION_CAP = 200
```

6. Deploy.

The first boot builds the Chroma index from the committed markdown documents and downloads the fastembed model. The app is ready when the chat input appears and the sidebar shows the data as-of date and indexed chunk count.

### Why the index is not committed

The index is generated output and depends on the fastembed model. Committing it would add a large binary directory and make the source of truth ambiguous. The app rebuilds it automatically when the documents change.

### Streamlit Cloud limitations

- The filesystem is ephemeral. `data/usage.db` and the index can be recreated after a restart, so the daily cap is best-effort rather than a billing control.
- Session uploads live only in the current browser session.
- The app is a demo, not a production multi-tenant service.
- If the app is idle, the first request after waking may take longer while the index and model load.

## 4. Post-deployment verification

Open the deployed app and check:

- Sidebar shows data as of `2026-11-01`.
- Sidebar shows a nonzero indexed chunk count.
- A document question returns a cited source.
- A data question returns a number and shows `get_sales_summary` or `run_sql_query` in Tool activity.
- A missing-evidence question returns `I don't know.`
- Uploading a small `.md` or `.txt` file makes it searchable in the same session.
- Reset conversation clears messages and resets the session counter.

Useful local equivalents:

```powershell
python -m src.health --json
python -c "from streamlit.testing.v1 import AppTest; at = AppTest.from_file('streamlit_app.py', default_timeout=120).run(); print('exceptions', len(at.exception), 'chat_inputs', len(at.chat_input))"
python eval/run_eval.py
```

## 5. Docker (self-hosting)

Build and run:

```powershell
docker build -t ops-copilot .
docker run --rm -p 8501:8501 --env-file .env ops-copilot
```

Or mount a secrets file:

```powershell
docker run --rm -p 8501:8501 -v "${PWD}/.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro" ops-copilot
```

The image uses Python 3.11, installs `libgomp1` for ONNX Runtime, runs as a non-root user, and exposes Streamlit on port `8501`. The index and model cache are created inside the container on first start; mount `data/` if you want them to persist.

Docker is optional. The local Docker daemon must be running.

## 6. MCP server

The MCP server is for local desktop or IDE clients. It uses stdio and does not need an LLM key.

```powershell
python mcp_server.py
```

Example client configuration:

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

The server exposes `search_documents`, `get_sales_summary`, `get_low_stock_items`, and `run_sql_query`. All tools are read-only. Restart the client after changing documents or the database so it can rebuild the index.

## 7. Troubleshooting

### `ANTHROPIC_API_KEY is not configured`

Add the key to `.streamlit/secrets.toml` locally or to the Streamlit Cloud Secrets panel. Do not put the key in a committed file.

### Index build fails or is empty

Check that `data/docs/` contains 13 markdown files and that `data/ops_copilot.db` exists. Remove `data/index/` and restart the app to force a rebuild. The first fastembed run needs network access to download the model.

### Model request fails

Check the provider, model name, key, and account quota. The UI shows a short error and does not expose the key. The eval runner prints the provider/model before starting.

### SQL is rejected

Only one read-only `SELECT` or `WITH ... SELECT` statement is allowed. Remove writes, DDL, `PRAGMA`, `ATTACH`, `sqlite_master`, and multiple statements.

### Daily cap is reached

The default is 200 questions per UTC day across the app, and 10 per browser session. Reset the session with **Reset conversation**. To change the cap, set `DAILY_QUESTION_CAP` in secrets and restart the app.

### Streamlit Cloud app sleeps

The free tier may sleep after inactivity. Wake it and allow time for the index/model to load. Usage counters and session uploads are not durable across restarts.
