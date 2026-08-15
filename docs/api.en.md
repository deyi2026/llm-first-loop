# llm_loop Public API Reference

> English version of docs/api.md (Chinese: docs/api.md)

> This document is for integrators: embedding the LLM-First Core Loop into your own application/script.
> For the full configuration options see `.env.example` and `docs/configuration.md`; for sample code see `examples/`.
> **Stable API declaration (B5)**: the symbols listed in the tables below (§1–§8) are the public stable
> interface; semantic changes require a version number bump (minor versions within 0.x may add, not
> break). Symbols not listed (internal: `_` prefix, mixins, `registry_*`) are considered private —
> do not depend on them externally.

---

## 1. Quick Assembly (Two Lines to Start)

```python
from llm_loop.config import load_env_file, load_settings
from llm_loop.factory import build_engine

load_env_file()              # Load config from the project root .env (environment variables take precedence)
engine = build_engine(load_settings())

# One-shot conversation (session auto-created): the simplest path
result = engine.run_single("Please read data/notes.txt and summarize")
print(result.final_answer)
```

## 2. Configuration Layer (`llm_loop.config`)

| Symbol | Description |
|:---|:---|
| `load_settings() -> Settings` | Assembles all configuration from environment variables; raises a `ValueError` with guidance when `LLM_API_KEY`/`LLM_BASE_URL` are missing |
| `load_env_file(path=None)` | Loads `.env` into environment variables (already-set environment variables take precedence; fail-open when the file is missing) |
| `Settings` | Dataclass for all configuration (read-only convention); key fields: `llm_model`/`max_iterations`/`history_max_chars`/`exec_mode`/`data_dir`, etc. |

## 3. Engine (`llm_loop.factory` / `llm_loop.core.loop.engine`)

### `build_engine(settings: Settings) -> LoopEngine`
Assembles all components (LLM client, memory, retrieval, tool registry, event log, approval audit) — **the only production assembly point**.

### `LoopEngine`
| Method | Description |
|:---|:---|
| `run(session_id: str, user_text: str, model=None) -> LoopResult` | Runs the full loop synchronously (tool loop blocks internally) |
| `run_single(user_text: str, model=None) -> LoopResult` | **One-shot convenience entry point**: automatically creates a new session and runs it (equivalent to `run(create(), text)`) |
| `run_stream(session_id, user_text, model=None) -> Iterator[StreamDelta]` | Streaming version: yields content deltas one by one, raises `StopIteration` carrying the `LoopResult` at the end |
| `session` | The assembled `SessionStore` (session CRUD) |
| `registry` | The assembled `ToolRegistry` (tool registration/execution) |

### Injecting a Custom Tool (B5)
```python
engine.registry.register(MyTool())   # Implements name/description/parameters/execute (see §5)
# After registration the AI can invoke it autonomously in the next loop (schema auto-injected)
```

### `LoopResult` Key Fields
`session_id` / `final_answer` / `rounds` / `tool_calls` (tool declaration trace) / `model_used` (truthfully records the actual model) / `tokens_in` / `tokens_out` / `truncated` / `reasoning_content`

## 4. Sessions (`llm_loop.core.session`)

| Method | Description |
|:---|:---|
| `SessionStore(sessions_dir, event_store=None, read_path_source="session_json")` | Session storage (JSONL + optional event sourcing) |
| `create() -> str` | Creates a new session, returns session_id |
| `load(session_id) -> Session` | Loads a session (fail-open on corruption) |
| `save(session)` / `append(session_id, message)` / `delete(id, confirm)` | Persist/append/delete (atomic writes) |
| `list_sessions()` / `get_meta(session_id)` | Session list/metadata |
| `fork(session_id, ...)` | Session fork (event log physically copied and inherited) |

## 5. Tool System (`llm_loop.tools`)

### Tool Protocol (Only 4 Items Needed to Register a New Tool)
```python
from llm_loop.core.message import ToolResult, ToolResultStatus

class MyTool:
    name = "my_tool"
    description = "When to use / when not to use / failure handling"
    parameters = {"type": "object", "properties": {...}, "required": [...]}  # JSON Schema

    def execute(self, **kwargs) -> ToolResult:
        # Return one of five statuses: SUCCESS / FAILURE / ERROR / TIMEOUT / BLOCKED (no faking success)
        return ToolResult(status=ToolResultStatus.SUCCESS, content="result text",
                          tool_call_id="", tool_name=self.name)
```

### `ToolRegistry`
| Method | Description |
|:---|:---|
| `register(tool)` | Registers a tool (same-name overwrite + warning) |
| `unregister(name) -> bool` / `dispose() -> int` | Unregister/clear (basis for hot updates/evolution rollback) |
| `execute(call: ToolCall) -> ToolResult` | Unified execution wrapper: argument validation → catastrophic safety → EXEC_MODE grading → approval → waterfall → timeout → five-status receipt |
| `execute_many(calls) -> list[ToolResult]` | Batch execution (read-only parallel / modification serial) |
| `schemas(lazy=False) -> list[dict]` | Tool schema list (lazy=index mode saves tokens) |
| `set_approval_callback(fn)` | Injects a human approval callback (EXEC_MODE intercepted items can be confirmed at the terminal) |

## 6. Message Model (`llm_loop.core.message`)

- `Message(role, content, source, tool_call_id=None, tool_name=None, status=None, ...)`
- `MessageSource`: `USER` / `SYSTEM` / `TOOL` (source truthfully recorded)
- `ToolCall(id, name, arguments)`: tool declaration (`tool_call_id` uniformly managed by the program)
- `ToolResult` + `ToolResultStatus` (five statuses, see above)

## 7. Web Embedding (`llm_loop.web`)

```python
from llm_loop.config import load_env_file, load_settings
from llm_loop.web import build_app

load_env_file()
app = build_app(settings=load_settings())   # FastAPI app (includes auth/upload/SSE endpoints)
# uvicorn.run(app, host="127.0.0.1", port=8902)
```

`build_app(settings=None, engine=None)`: two-argument assembly; `app.state.engine` single instance.
Endpoint quick view: `POST /api/v1/chat` (body: `{message, session_id?, model?}`),
`POST /api/v1/chat/stream`, `GET /api/v1/sessions`, `POST /api/v1/upload`, `GET /health`
(auth: loopback exemption + `WEB_API_KEY` enforced remotely).

**Headless service mode (B5)**: pure-API embedding without a UI — see `examples/04_headless_service.py`
(assembly + sync/streaming chat endpoints, ~20 lines); the core is a `build_engine(load_settings())`
single instance + the two entry points `engine.run_single` / `engine.run_stream` (locked by signature
snapshot tests).

## 8. CLI (`python -m llm_loop.cli`)

- Single message: `python -m llm_loop.cli "message"`
- Interactive mode: `python -m llm_loop.cli --interactive`
- Session management: `list` / `delete` / `archive` / `unarchive` / `search` / `extract`
- Evolution review: `evolve-list` / `evolve-review` / `evolve-complete`
- Data tools: `export-distill` / `event-*` (inventory/migrate/replay/reconcile/rollback/retire)

## 9. Extension Points at a Glance (B-route planning)

| Extension surface | Entry point |
|:---|:---|
| New LLM Provider | `MODEL_PROVIDERS` registry JSON + `llm_loop.llm.providers` |
| New tool | `ToolRegistry.register` (protocol see §5) |
| Semantic retrieval | `EMBEDDING_PROVIDER` (none/hash/api) + `memory.retriever` |
| Event sourcing | `EVENT_LOG_ENABLED` + `event_log` package |
| Human approval | `set_approval_callback` (wired up in CLI interactive mode) |
| Skill experience | `EXPERIENCES_DIR` + `tools_skills` (SKILL.md mechanism) |
