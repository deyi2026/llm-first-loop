# Evidence Recoverability R11 — Long Tool Session / Compression / Cache Stability Stress v1

Date: 2026-08-26
Status: **PRE-REGISTERED BEFORE ANY R11 REAL PROVIDER REQUEST**
Model: `deepseek/deepseek-v4-flash`
Treatments: `off` vs `enforce` using the same current mirror source tree
A3: **STOPPED**
Production `.env` / `data/providers.json`: **must remain unchanged**

## Objective

Return to the original system goal after R9/R10 source-resolution closure: verify that long real production-loop sessions remain structurally stable when tool history grows and compression occurs, and that Evidence enforce reduces program-induced physical source reacquisition without creating cache-prefix instability.

R11 uses the actual Web -> LoopEngine -> provider -> ToolRegistry path. It does not use the simplified R10 provider loop.

## Isolation

Each condition runs in a fresh subprocess with:

- dedicated Web port;
- dedicated `DATA_DIR` and `LFL_DATA_DIR` under `data/audit/evidence_r11/runtime/<mode>`;
- a copied provider registry where only DeepSeek `history_budget_chars` is changed to **50,000** for stress;
- `EVIDENCE_MODE=off` or `EVIDENCE_MODE=enforce` as subprocess-only override;
- same source files, user-turn script, model, repository cwd and all other loaded `.env` settings.

The 50K budget is a stress fixture, not a production recommendation. Global `.env` remains `HISTORY_MAX_CHARS=1,000,000`; production provider registry remains unchanged.

Each mode receives one unscored warmup session first so its own static system+tools prefix can be cached before the measured long session.

## Fresh source fixtures

Ten deterministic text files are generated once and shared by both conditions. Each is ~20K+ chars and has one unique middle marker `R11-CODE-XX: <token>` outside simple head/tail projection windows. Source bytes are hashed before execution.

The measured session has 12 user turns:

- turns 1-10 introduce one new source file each using an explicit full file-read task;
- selected turns also request codes from earlier files, without telling the model whether/how to recover them;
- turn 11 requests several earlier codes with no new source;
- turn 12 requests all ten codes.

No user message says "do not reread", "never repeat", or equivalent.

## Mechanical event metrics

From the isolated event log and request usage/window events:

### Prompt/cache structure

- API request count;
- `request.meta.tools_count` unique values;
- `request.meta.budget` unique values;
- model unique values;
- `history_chars` curve;
- exact `request.usage` prompt/cache hit/miss curve;
- `cache.window` hit ratio, `boundary_msg_index`, `cached_msgs`, `new_msgs`;
- cache-boundary backward jumps;
- backward jumps not preceded by `context.compressed` since the prior cache window.

### Compression

- `context.compressed` count;
- compressed message indices;
- compression streak across consecutive API request intervals;
- maximum compression streak;
- maximum number of compression events between adjacent `request.meta` events.

### Source/Evidence

Assistant declarations are paired to tool results by `tool_call_id`.

- declared `read_file` count and repeated source-path declarations;
- physical `read_file` count;
  - `off`: every successful read_file tool result is physical;
  - `enforce`: `metadata.source_execution_performed=true` is physical, false is Evidence reuse;
- physical repeated source-path count;
- Evidence reuse count;
- recovery tool declarations/counts (`list_evidence/search_evidence/read_evidence/search_archive`).

### Correctness/protocol

- each of 12 Web responses must contain every code mechanically required by that user turn;
- protocol/tool errors are counted from tool result status and Web/LLM failure responses.

## Frozen per-mode gates

1. service starts healthy and measured session completes 12/12 user turns.
2. expected-code correctness >= 11/12 turns; final turn contains all 10 codes.
3. one model only: DeepSeek flash.
4. `tools_count` has exactly one value within the measured session.
5. `budget` has exactly one value and equals stress budget 50,000.
6. no tool-protocol error / unresolved LLM error.
7. maximum consecutive compression-request streak < 5.
8. maximum compression events between adjacent request.meta <= 3.
9. cache boundary backward jumps without an intervening compression event = 0.
10. after the first two API requests, no run of 3 consecutive `cache.window.hit_ratio < 0.50`.
11. median `cache.window.hit_ratio` after the first two API requests >= 0.70.

## Frozen paired gates

12. enforce physical repeated-source-path count <= off.
13. enforce total physical read_file count <= off total physical read_file count + number of distinct source files introduced (guard against runaway refresh; not a raw-call minimization target).
14. enforce compression event count <= off compression event count.
15. enforce maximum compression streak <= off maximum compression streak + 1.
16. enforce post-warmup median cache hit ratio is not worse than off by more than 0.10 absolute.
17. enforce prefix-cliff count (3+ consecutive hit ratio <0.50 after request 2) <= off.

Evidence reuse count is diagnostic, not required >0: a model may choose `search_evidence` directly and never declare a covered source fallback.

## Interpretation

PASS means R3/R6/R9 are eligible for rollout-design review under long-session compression/cache pressure. FAIL is classified into correctness, physical source reacquisition, compression storm, or cache-structure instability. No post-hoc thresholds or prompt edits are allowed.
