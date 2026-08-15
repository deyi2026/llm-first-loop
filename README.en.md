# LLM-First Core Loop

> **License**: [Apache-2.0](LICENSE) ｜ **Version**: 0.6.7 ｜ **Status**: Open-source framework-ization (Track B) in progress ｜ **中文版**: [README.md](README.md)

The LLM is the core, and every action revolves around it. Architecture core = **message in → understand → act → answer honestly → remember**.

Program code assists the LLM (timely feedback, honest feedback), never constrains it. The LLM receives honest feedback on both success and failure alike, and can inspect the architecture's runtime state at any time and correct itself autonomously.

**Positioning**: an "AI-first" (LLM-first) agent runtime (Harness) — program minimalism + documentation-rule-driven + AI-autonomous evolution loop (self-evaluation → evolution proposal → human review → tiered execution → full-chain audit). Three channels (CLI / Web / Feishu bridge), with built-in memory, retrieval, event sourcing, and an evaluation suite.

## Architecture Principles (AI Perspective)

- **Program minimalism**: judgments that the AI can make autonomously (guided by documentation rules, `docs/ai_rules.md`) stay out of code wherever possible. Code keeps only what the AI cannot do on its own (real tool execution, storage, catastrophic-safety hard bounds).
- **Programs are convenience and complement, not constraint**: tool success/failure/anomaly outcomes are constructed truthfully (marked `[状态: xxx]`), errors pass through in full — no silent degradation.
- **Fault tolerance first**: a program-component failure surfaces to the AI truthfully as `[程序异常]` → the loop continues, without affecting the LLM's performance.
- **AI autonomy rules**: honest self-check / parameter self-governance / stagnation self-adjustment / program-fault handling (see `docs/ai_rules.md` — the single source of truth for rules, embedded in the system prompt).

## AI-Perspective Quick Read (T4, spec.md 5.3.1/5.5.1)

> Role declaration of the program / documentation rules / architecture (AI-first perspective):

- **Program = senses + hands and feet**: provides information (`architecture_status` perceives context/model/anomalies/todos) + an execution channel (tools such as `adjust_strategy`/`retry_tool`/`switch_model`) + hard bounds (catastrophic safety / protocol constraints / storage); it does not think for the AI, nor choose for the AI.
- **Documentation rules = brain constraints**: `docs/ai_rules.md` is the single source of truth (SoT) for rules; RULE-AI-00~07 are embedded in the system prompt and followed autonomously by the AI; the program does not re-implement the rules.
- **Architecture = serving the AI's execution capability**: program minimalism (what the AI can do autonomously + via rules needs no program), programs are convenience and complement rather than constraint, avoiding program errors affecting the LLM.
- **Hard constraints are not handed over**: the C1-C6 protocol (tool_call_id binding, etc.) / FR-SAFE-01 catastrophic safety / data integrity remain hard-executed by the program (the AI cannot do them itself); only decision-type judgments are handed over to AI + rules.

## Quick Start

```bash
# 1. Setup
cd llm-first-loop
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# 2. Configure keys (LLM_MODEL defaults to deepseek-v4-flash if unset)
export LLM_API_KEY=sk-xxx
export LLM_BASE_URL=https://api.deepseek.com/v1
# export LLM_MODEL=deepseek-v4-flash   # Optional: deepseek-v4-flash (default) / deepseek-v4-pro
# export LLM_THINKING_MODE=enabled     # DeepSeek V4 thinking mode (enabled by default)
# export LLM_REASONING_EFFORT=high     # Reasoning effort low/high/max (default high)

# 3. Minimal loop: a single message
.venv/bin/python -m llm_loop.cli "Please read data/notes.txt and summarize the content"

# 4. Interactive mode (--session reuses an existing session)
.venv/bin/python -m llm_loop.cli --interactive
.venv/bin/python -m llm_loop.cli --session <id> "continue the conversation"

# 5. Tests
.venv/bin/python -m pytest tests/ -q
```

## Features

- **Core loop**: LoopEngine five-phase state machine (message in → understand → act → answer honestly → remember)
- **Strict function calling**: tool_call_id is uniformly managed by the program; it never produces a tool message without an id (compatible with DeepSeek/OpenAI strict APIs)
- **Architecture introspection**: the LLM can call `architecture_status` to query the architecture's runtime state; anomalies are proactively reported via `[架构上报]`; correction tools (adjust_strategy / retry_tool / refresh_config) allow autonomous fixes
- **Evolution proposals land and execute automatically** (M12 deepening + M16/M17 audit): the AI can submit architecture evolution proposals via `submit_evolution` (a pure suggestion channel; the receipt includes "awaiting evolve-review review" guidance); `EVOLVE_LOCAL_EXEC` three-tier permission (0=proposals only / 1=whitelisted partial execution / 2=full execution); after a human `evolve-review <id> accepted`, execution proceeds automatically per the permission tier (state advancement + audit + execution guidance); **the execution actions/verification/rollback are done autonomously by the AI** (carried by the correction tools `adjust_strategy`/`retry_tool`/`refresh_config` under the sub-rules of RULE-AI-06; the program does not execute/verify/roll back for the AI, and verify_result=unverified is labeled truthfully); after execution the AI registers "done + verification conclusion" via the `evolution_complete` tool (executing→executed); boundary-crossing evolutions are registered manually via the CLI `evolve-complete` (executor=human); while an executing evolution exists in the loop, `[演进执行提醒]` is injected automatically; the full-chain audit log `evolution_exec_log` is searchable
- **AI self-evaluation and improvement** (M12 deepening + M16 audit): the AI can proactively initiate a five-dimension self-evaluation via `self_evaluate` (success rate / tool efficiency / honesty / stagnation rate / anomaly rate; sources traceable, insufficient samples labeled truthfully); periodic/milestone triggers only prompt, never force (the timing of anomaly-triggered evaluation is left to the AI's discretion, RULE-AI-06); evaluation results are persisted to `self_eval_log` and searchable; bidirectional traceability from evaluation to proposal (`evidence="eval:SE-..."`); improvement execution uses the same permission tiers, and `SelfEvalComparison` supports before/after comparison
- **No information loss**: when the context grows too long, a compressed archive is stored separately (retrievable via `search_archive`); `search_records` provides unified search across history records / memory / archives (queryable and searchable)
- **Smart memory**: LLM semantic summarization (`SUMMARY_MODE`), semantic retrieval (`EMBEDDING_PROVIDER`), standalone memory extraction (session end / periodic / manual)
- **Multi-session management**: CLI subcommands `list / delete / archive / unarchive / search / extract` + `--session` reuse
- **Model system** (M47-M50): `model_catalog` to inspect the catalog / `switch_model` for autonomous switching (reason audited to disk; the AI holds the decision right); Provider registry + `MODEL_FALLBACKS` emergency fallback chain (automatic emergency fallback only when the default-assembled model fails, honestly labeled; models explicitly chosen by the user are never downgraded); model-window-adaptive history budget (tightened/relaxed per the current model's context)
- **Dual-channel access** (Web + Feishu bridge): Web management UI (FastAPI :8902) + Feishu long-connection bridge; with `FEISHU_OWNER_OPEN_ID` configured, both channels share the same session (one side speaks, the other can continue the same context); the Feishu bridge has built-in dead-lock protection (SDK lock-leak runtime patching + watchdog heartbeat + health check judged by heartbeat freshness)
- **Distillation dataset export** (export_distill, pure read-only thin shell): the `export-distill` subcommand exports `data/sessions/*.json` session traces into a ReAct JSONL distillation set with reasoning chains + a structured statistics report — segment task segments at user boundaries → segment-level filtering on `status=success` + closed-loop completeness (filter reasons counted by category) → ReAct triple samples (thought/action/observation byte-identical to the source; missing reasoning chains honestly set to null) → JSONL (`ensure_ascii=False`, over-long content never truncated) + report (passed + filtered = total segments, closed-loop reconciliation); produces data only — no training, no splitting/augmentation/desensitization; corrupted files fail-open and are honestly labeled and skipped; existing output is rejected by default (`--force` overwrites); source session files are read-only with zero modification
- **Event-sourced single source of truth** (D1 event log): the `data/event_logs/<session_id>.jsonl` event log is the single source of truth for traces (5 event types: session.created / message.appended / context.compressed / session.meta_changed / session.forked); events are appended at runtime via fail-open hooks; `event-replay` replays to rebuild derived views; `event-inventory` read-only inventory (hash + mtime, zero modification) → `event-migrate` migrates legacy session JSON into event logs (auto-backup to `event_logs/_backup/<ts>/` before migration; missing fields in legacy v3 sessions get defaults automatically; idempotent — a second migration migrates 0) → `event-verify` reconciles the replayed view against the source field by field (differences honestly labeled) → `event-rollback` byte-exact restore from the backup area (`--remove-events` restores the event log); with `EVENT_LOG_ENABLED=0` event writes are a no-op, and the three legacy stores are kept for dual-track reconciliation
- **D1 follow-up batch** (d1_es_followup): **D3 session fork** — `session-fork` / `POST /api/v1/sessions/{id}/fork` triggers a physical copy-inherit of the event log (keeps type/ts/payload, reassigns seq/event_id/session_id) + the session.forked event carries fork metadata + the source session stays byte-identical + the new session's events can be replayed independently; **retirement of the three stores** — `event-retire` orchestration (backup → dual-track reconciliation → archive action_trace/session JSON → switch read path to `READ_PATH_SOURCE=event_log`) + `event-retire-rollback` byte-exact restore; switching happens only after full reconciliation passes (no switch, no retirement on inconsistency); **event-log rotation** — multi-segment directories `<sid>/<segment_seq>.jsonl` (three triggers: size / days / session end) + `event-rotate-status` segment listing + cross-segment replay byte-identical + archived segments read-only; **D4 filter hooks** — a HookChain at the `EventStore.append` entry (filter to drop / desensitize to mask / transform to convert, ascending by priority) + audit persisted to `_hook_audit.jsonl` (without sensitive raw-payload content) + fail-open so anomalies never block + `event-hooks` CLI (list/test) + an empty hook chain by default, zero behavior, zero regression
- **Catastrophic safety**: the only hard bound = irreversible deletion / system destruction; everything else is allowed through with feedback; **known catastrophic patterns hard-blocked + full-block audit** (`data/audit/safety_blocks.jsonl`) — before judging, `$VAR`/`~` expansion + compound-command splitting + recursive inspection of shell/python `-c` payloads (blocks rm -rf of root/home/system directories, mkfs, dd writing to block devices, fork bombs, curl-piped execution, writes to critical system areas, find -delete/-exec rm); honestly labeled: not a complete sandbox — stronger isolation layers on top via EXEC_MODE tiers and system-level sandboxes
- **Data governance** (T3): compressed-archive sharding (`ARCHIVE_SEGMENT_BYTES`, default 100MB; past the threshold a new `<sid>-N.jsonl` segment opens; retrieval scans segments in reverse order + a sidecar-index fast path + full-text completion, with limit-truncation semantics equivalent; legacy unindexed segments fall back to a full-text scan); Feishu heartbeat-history rotation (`FEISHU_HEARTBEAT_HISTORY_MAX_MB`; past the threshold the current file rotates to `.1`, keeping 1 copy)
- **Human approval flow** (T5a): EXEC_MODE-blocked items can be released via terminal confirmation in CLI interactive mode (`_cli_approval_prompt`; without a terminal, fail-closed rejection); approval audits persist to `data/audit/approval_audit.jsonl` (decision/tool/argument summary, no secrets); catastrophic-safety hard blocks cannot be approved
- **symlink write protection** (T5b): edit_file refuses writes when the write path contains a symlink (itself or a parent directory) to prevent escaping (fail-closed + realpath guidance); read_file honestly labels reads of symlinks without refusing them
- **Evaluation suite** (T4): a fixed evaluation set `tests/eval_sets/scenarios_v1.json` (6 scenarios; verdict criteria derived from an internal empirical baseline) + a runner `scripts/run_eval.py` (real LLM / `--dry` pipeline validation; verdict + Wilson CI + reports persisted to `docs/metrics/`) + automatic CI nightly runs
- **CI + versioning** (T7/B11): GitHub Actions three-gate checks (pytest/ruff/pyright) + nightly real evaluation; semantic versioning v0.6.7; Release Drafter (PR titles auto-categorized into the changelog) + tag-triggered gate re-check + Release draft (institutionalized release cadence)
- **Plugin-style Skills** (B3): automatic directory scan of `skills/<name>/SKILL.md` (`SKILLS_DIR`, default ./skills); the AI discovers and loads external skills via `skill_list`/`skill_load` and executes them — external developers extend framework capabilities with zero code; corrupted/missing files fail-open and are skipped; the repo ships example skills (`skills/`: notebook-session/incident-report) discoverable directly via `skill_list`
- **web_fetch SSRF intranet blocking** (HARNESS-03 + P0-2/P0-3 deepening): `WEB_FETCH_BLOCK_PRIVATE` (on by default) blocks private/loopback/link-local/reserved address ranges (dual path: IP literals + DNS resolution) against cloud-metadata and other intranet probing; on a hit it returns BLOCKED `[内网拦截]`; **per-hop redirect validation** (both httpx and curl disable automatic following; a manual loop with a cap of 5 hops re-validates every hop — a public URL that 302-redirects to the intranet no longer leaks); **DNS-rebinding narrowing** (curl `--resolve` pins the validated IP for pre-connect pinning; httpx re-checks the actual peer IP after connecting and drops on a hit — honestly labeled: on the httpx channel the GET has already been sent; to prevent data readback, stronger isolation uses the curl pinning channel)
- **Context budget warning** (HARNESS-04): when context usage reaches ≥80% of the budget, a one-time `[预算预警]` is injected (with usage % and char count); "compress/wrap up" decisions belong to the AI — the program never auto-compresses
- **Orphan tool_calls synthetic receipts** (HARNESS-01): when the `run_stream` client is interrupted, a "cancelled" receipt is written automatically and saved immediately, so no orphan declaration ("declared but no receipt") is produced (the root cause of strict FC protocol 400s)
- **`request.meta` event** (HARNESS-02): a per-round LLM request snapshot goes into the event log (round/model/tools_count/history_chars/budget); replay tells exactly "which model was used / which tools were attached" at the time
- **Headless service mode** (B5): UI-free pure-API embedding — `examples/04_headless_service.py` (`build_engine` single instance + sync/streaming chat endpoints in ~20 lines); public API signature snapshot tests lock it (preventing semantic drift)
- **Multi-provider cost-routing enhancement** (B6): `switch_model` success receipts inject the target model's cost tier (cost_tier) + capability semantics (thinking/reasoning/long_context/multimodal) + context window (missing metadata honestly labeled; judgment belongs to the AI)
- **Eval-set contribution guide** (B7): `docs/eval_scenarios.md` — external contributors add a scenario per the schema in ~30 minutes (verdict registration + dry validation + PR acceptance checklist)

## CLI Subcommands

```bash
.venv/bin/python -m llm_loop.cli list                  # list sessions (--archived includes archived)
.venv/bin/python -m llm_loop.cli delete <id> [--yes]   # delete a session (requires confirmation)
.venv/bin/python -m llm_loop.cli archive <id>          # archive a session
.venv/bin/python -m llm_loop.cli unarchive <id>        # unarchive a session
.venv/bin/python -m llm_loop.cli search <query>        # search sessions
.venv/bin/python -m llm_loop.cli extract <id>          # manually trigger standalone memory extraction
.venv/bin/python -m llm_loop.cli evolve-list [status]  # list evolution proposals (human review entry)
.venv/bin/python -m llm_loop.cli evolve-review <id> <accepted|rejected>  # review an evolution proposal (accepted + permission allowed → auto-execute)
.venv/bin/python -m llm_loop.cli evolve-complete <id> "<result note>"  # human completion registration (boundary-crossing evolution → executed, executor=human)
.venv/bin/python -m llm_loop.cli export-distill [--input-dir DIR] [--output FILE] [--report FILE] [--force]  # export distillation dataset (thin shell, read-only; ReAct JSONL + statistics report)
.venv/bin/python -m llm_loop.cli event-inventory [--event-logs-dir DIR]  # event log inventory (read-only: scale numbers + gaps; zero file modification)
.venv/bin/python -m llm_loop.cli event-migrate [--event-logs-dir DIR] [--force]  # migrate legacy sessions into event logs (backup to _backup/<ts>/ first; idempotent)
.venv/bin/python -m llm_loop.cli event-verify [--all|--session ID] [--event-logs-dir DIR]  # reconcile the replayed view against the source field by field
.venv/bin/python -m llm_loop.cli event-rollback [--session ID] [--remove-events]  # restore source files from the backup area (optionally remove event logs)
.venv/bin/python -m llm_loop.cli session-fork --session <id> [--fork-point N] [--summary ...]  # session fork (physical copy-inherit of the event log + session.forked event)
.venv/bin/python -m llm_loop.cli event-retire [--data-dir DIR] [--force]  # retire the three stores (backup → reconcile → archive → switch read path)
.venv/bin/python -m llm_loop.cli event-retire-rollback --data-dir DIR --backup-dir <dir>  # retirement rollback (byte-exact restore + switch read path back)
.venv/bin/python -m llm_loop.cli event-rotate-status [--data-dir DIR] [--session <id>]  # event log rotation segment listing
.venv/bin/python -m llm_loop.cli event-hooks [--data-dir DIR] {list,test}  # filter hook management (list registered / test with a sample event)
.venv/bin/python -m llm_loop.cli --session <id> "message"  # reuse a session to continue the conversation
```

## Configuration (Full Template in .env.example)

| Variable | Default | Description |
|:---|:---|:---|
| `LLM_API_KEY` / `LLM_BASE_URL` | — | Required |
| `LLM_MODEL` | deepseek-v4-flash | Model (fallback chain: explicit > OPENSYGAI_DEEPSEEK_DEFAULT_MODEL > built-in) |
| `LLM_THINKING_MODE` | enabled | DeepSeek V4 thinking-mode switch (not sent automatically for non-DeepSeek) |
| `LLM_REASONING_EFFORT` | high | Reasoning effort low/high/max |
| `LLM_MAX_ITERATIONS` | 40 | Max loop rounds per run (raise for tool-intensive tasks; at 80% a [轮数预警] is injected and the AI can raise it via adjust_strategy; hard cap 500) |
| `SUMMARY_MODE` | off | LLM summarization: off/sync/async |
| `EMBEDDING_PROVIDER` | none | Semantic retrieval: none/hash/api |
| `EXTRACT_ENABLED` | 1 | Standalone memory extraction switch |
| `VALIDATE_SEMANTIC` | 0 | Declaration-receipt semantic matching (off by default) |
| `EVOLVE_LOCAL_EXEC` | 0 | Evolution execution permission tiers: 0=proposals only / 1=whitelisted partial execution / 2=full execution (legacy boolean compatible) |
| `EVOLVE_EXEC_WHITELIST` | empty | Execution whitelist (at tier 1: comma-separated scope/module/action types; empty = not configured, no auto-execution) |
| `SELF_EVAL_ENABLED` | 1 | Self-evaluation capability switch (self_evaluate tool) |
| `SELF_EVAL_REMIND_ENABLED` | 1 | Trigger-reminder switch (prompt only, never force) |
| `SELF_EVAL_INTERVAL_ROUNDS` / `SELF_EVAL_MIN_SAMPLES` / `SELF_EVAL_SPAN` | 50/5/50 | Periodic trigger interval / insufficient-sample threshold / aggregation window |
| `SYSTEM_PROMPT_EXTRA` | — | Append custom AI rules (program minimalism — no code changes needed) |
| `HISTORY_MAX_CHARS` | 100000 | History context budget (chars) submitted to the LLM; default 100K (≈50K tokens); adjustable per model window (raise for 1M-window models, lower for small-window models); too large a budget overflows the window and fails/times out every model call |
| `MODEL_FALLBACKS` | empty | Fallback chain (comma-separated `provider/model`, e.g. `deepseek/deepseek-v4-flash,local/qwen3.6-27b-fable-fusion-711-uncensored-heretic-nm-dau-neo-max-mtp`); empty = fallback disabled |
| `EVENT_LOG_ENABLED` | 1 | Event-sourced single-source-of-truth switch (append-write to `data/event_logs/<session_id>.jsonl`; 0 = event writes are a no-op) |
| `EVENT_LOGS_DIR` | empty | Event log directory override (empty = derived from data_dir as `data/event_logs`) |
| `READ_PATH_SOURCE` | session_json | Read-path dispatch (session_json existing / event_log rebuilt by replay) |
| `EVENT_LOG_ROTATE_BYTES` | 10485760 | Event log rotation size threshold in bytes (0=disabled) |
| `EVENT_LOG_ROTATE_DAYS` | 30 | Event log rotation day threshold (0=disabled) |
| `EVENT_LOG_ROTATE_ON_SESSION_END` | 1 | Rotate when the session ends |
| `EVENT_HOOKS_CONFIG` | empty | Filter-hook config file path (empty = hook chain default empty, zero behavior) |
| `ARCHIVE_SEGMENT_BYTES` | 104857600 | Compressed-archive per-file shard threshold (default 100MB; 0=no sharding; past the threshold a new `<sid>-N.jsonl` segment opens; retrieval scans segments in reverse order + sidecar-index fast path) |
| `FEISHU_HEARTBEAT_HISTORY_MAX_MB` | empty | Feishu heartbeat-history rotation threshold (MB; empty = unlimited; past the threshold the current file rotates to `.1`, keeping 1 copy) |

> **Config loading (M63)**: all three channels — CLI / Web / Feishu — load uniformly from the project `.env` (environment variables take precedence).
> After editing `.env`: the CLI takes effect immediately; for web/feishu run `bash scripts/restart_system.sh restart` for a one-click restart.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (project philosophy / gates / PR process) and [CHANGELOG.md](CHANGELOG.md) (public change log).

## Documentation

- Quick start: `examples/` (01 minimal CLI loop / 02 Web embedding / 03 custom tool registration)
- Public API reference: `docs/api.md` (assembly / engine / sessions / tools / Web / CLI / extension points)
- Configuration reference: `docs/configuration.md` (grouped configuration tables + quick reference for common pitfalls)
- Event-sourcing design: `docs/event_sourcing.md` (single source of truth + migration/rollback guide)
- Feishu rendering support matrix: `docs/feishu_render_matrix.md` (supported Markdown feature scope)
- Development methodology: `docs/development_methodology.md` (SoT first / honest recording / zero-regression discipline)
- Eval-set extension guide: `tests/eval_sets/README.md` (scenario schema + contribution steps)
- Documentation index: `docs/INDEX.md`
- AI autonomy rules (single source of truth for rules): `docs/ai_rules.md`
- Open-source framework-ization roadmap: `docs/ROADMAP-B-20260814.md`
- Development-process specs (spec/design/tasks) are local CodeArts workflow documents and are not distributed with the open-source repo.
