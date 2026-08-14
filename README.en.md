# LLM-First Core Loop

> **License**: [Apache-2.0](LICENSE) ｜ **Version**: 0.3.0 ｜ [中文文档 (Chinese README)](README.md)

An **LLM-first agent runtime (harness)**: the model is the core, and every action revolves around it.
Architecture core = **message in → understand → act → answer honestly → remember**.

Program code is an *aid* to the model (honest, timely feedback), never a constraint. The model
gets truthful feedback on success and failure alike, and can inspect the architecture at runtime
and correct itself autonomously.

**Differentiators**: program-minimalism philosophy (rules-as-docs, AI autonomy), a self-improvement
loop (self-evaluation → evolution proposals → human review → tiered execution → full audit trail),
three access channels (CLI / Web / Feishu bridge), memory, retrieval, event sourcing, and a built-in
evaluation suite.

## Quick Start

```bash
# 1. Setup
cd llm-first-loop
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# 2. Configure keys (LLM_MODEL defaults to deepseek-v4-flash)
export LLM_API_KEY=sk-xxx
export LLM_BASE_URL=https://api.deepseek.com/v1

# 3. Minimal loop: one message
.venv/bin/python -m llm_loop.cli "Please read data/notes.txt and summarize"

# 4. Interactive mode (--session reuses an existing conversation)
.venv/bin/python -m llm_loop.cli --interactive
.venv/bin/python -m llm_loop.cli --session <id> "continue the conversation"

# 5. Tests
.venv/bin/python -m pytest tests/ -q
```

## Embedding in Your App

```python
from llm_loop.config import load_env_file, load_settings
from llm_loop.factory import build_engine

load_env_file()
engine = build_engine(load_settings())
result = engine.run(engine.session.create(), "summarize data/notes.txt")
print(result.final_answer)
```

See `examples/` (minimal CLI loop / Web embed / custom tool) and `docs/api.md` for the full
public API reference.

## Architecture Principles

- **Program minimalism**: anything the AI can decide itself (guided by rule docs) stays out of code;
  code keeps only what the AI cannot do alone (real tool execution, storage, catastrophic-safety hard bounds).
- **Programs aid, never constrain**: tool outcomes are reported truthfully (`[status: xxx]`), errors pass
  through in full — no silent degradation.
- **Fault tolerance first**: component failures surface as `[程序异常]` (program anomaly) and the loop
  continues; the model's agency is never blocked by program bugs.
- **AI autonomy rules** (single source of truth: `docs/ai_rules.md`): honest self-check / parameter
  self-governance / stagnation self-adjustment / program-fault handling — embedded in the system prompt.

## Features

- **Five-phase core loop** (LoopEngine): message in → understand → act → answer honestly → remember
- **Strict function calling**: tool_call_id managed by the program (DeepSeek/OpenAI strict API compatible)
- **Architecture introspection**: `architecture_status` + correction tools (`adjust_strategy` / `retry_tool`
  / `switch_model` / `refresh_config`) — the AI inspects and fixes the runtime itself
- **Self-improvement loop**: `self_evaluate` (five-dimension metrics, traceable) → `submit_evolution`
  → human `evolve-review` → tiered auto-execution (`EVOLVE_LOCAL_EXEC` 0/1/2) → audited end-to-end
- **No information loss**: overflow archives + `search_archive` retrieval; `search_records` unified search
- **Smart memory**: LLM summaries (`SUMMARY_MODE`), semantic retrieval (`EMBEDDING_PROVIDER`), independent
  memory extraction
- **Multi-session CLI**: `list / delete / archive / unarchive / search / extract` + `--session`
- **Model system**: `model_catalog` / `switch_model` (audited, AI decides), provider registry,
  `MODEL_FALLBACKS` emergency chain (default-assembled model only, honestly labeled)
- **Three channels, one context**: CLI + Web (FastAPI :8902) + Feishu long-connection bridge,
  cross-channel shared session
- **Event sourcing** (single source of truth): append-only event logs, replay/verify/rollback/migrate
- **Evaluation suite**: fixed scenario set + runner (`scripts/run_eval.py`, real LLM or `--dry`),
  Wilson CI constraints, CI nightly
- **Safety**: catastrophic hard bound (irreversible deletion/system destruction only), EXEC_MODE tiers,
  human approval flow (CLI interactive), symlink write protection, secret-in-env-only

## CLI Subcommands

```bash
.venv/bin/python -m llm_loop.cli list | delete <id> [--yes] | archive <id> | unarchive <id>
.venv/bin/python -m llm_loop.cli search <query> | extract <id>
.venv/bin/python -m llm_loop.cli evolve-list | evolve-review <id> <accepted|rejected> | evolve-complete <id> "note"
.venv/bin/python -m llm_loop.cli export-distill [--input-dir DIR] [--output FILE] [--report FILE] [--force]
.venv/bin/python -m llm_loop.cli event-inventory | event-migrate | event-verify | event-rollback | event-retire | event-rotate-status | event-hooks
.venv/bin/python -m llm_loop.cli session-fork --session <id> [--fork-point N]
.venv/bin/python -m llm_loop.cli --session <id> "message"
```

## Configuration

Full template in `.env.example`. Key variables:

| Variable | Default | Description |
|:---|:---|:---|
| `LLM_API_KEY` / `LLM_BASE_URL` | — | Required |
| `LLM_MODEL` | deepseek-v4-flash | Default model |
| `LLM_MAX_ITERATIONS` | 40 | Max loop rounds per run (`[轮数预警]` at 80%, AI can raise via adjust_strategy, hard cap 500) |
| `HISTORY_MAX_CHARS` | 100000 | History budget in chars (≈50K tokens) |
| `SUMMARY_MODE` | off | LLM summarization: off/sync/async |
| `EMBEDDING_PROVIDER` | none | Semantic retrieval: none/hash/api |
| `EXEC_MODE` | (unset) | Command tiers: readonly/allowlist/blocked (unset = unrestricted) |
| `EVENT_LOG_ENABLED` | 1 | Event sourcing switch |
| `ARCHIVE_SEGMENT_BYTES` | 104857600 | Archive file sharding threshold (100MB) |

CLI/Web/Feishu all load `.env` (env vars take precedence). After editing `.env`:
`bash scripts/restart_system.sh restart`.

## Documentation

- Examples: `examples/` (minimal loop / web embed / custom tool)
- Public API reference: `docs/api.md`
- Docs index: `docs/INDEX.md` (public-surface principle: only run-required + user-facing docs ship)
- AI autonomy rules (single source of truth): `docs/ai_rules.md`
- Open-source roadmap (B track): `docs/ROADMAP-B-20260814.md`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## Development

- Python 3.13+, `pip install -e ".[dev]"`
- Quality gates: `pytest tests/ -q -m "not real_llm"` + `ruff check src tests scripts` + `pyright src --pythonpath python`
- CI: GitHub Actions (three gates on push/PR; nightly real-LLM smoke + eval with `DEEPSEEK_API_KEY` secret)
