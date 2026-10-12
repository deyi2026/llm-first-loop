# FC2-B Bounded Semantic Operation — Ornith 6-row Qualification Protocol v0.1

Status: **FROZEN BEFORE MODEL EXECUTION**

## Question

Can the already-mechanically-qualified `browser_semantic_operation` surface complete the same three Browser tasks, twice each, under the same local Ornith/runtime/sampling/12-round envelope, without exposing the old atomic micro-control surface to the model?

## Single treatment

Model-visible tools are exactly:

1. `browser_semantic_operation`
2. `get_tool_schema`
3. `read_evidence`

`browser_perceive`, standalone typed waits, `browser_semantic_execute`, `browser_action`, Playwright/CDP primitives, search/list Evidence, Methods, and cloud fallbacks are **not model-visible**. The bounded operation still executes the already-qualified perception/wait/semantic-execute/action stack internally, so durable ActionReceipts remain the physical-effect oracle.

`TOOL_SCHEMA_LAZY=1` remains frozen: the initial provider wire carries the compact top-level `clauses` contract, while `get_tool_schema` is the explicit on-demand path to the full recursively closed six-branch schema. The execution manifest freezes hashes for both the lazy wire surface and the full schema; they are not conflated.

This is deliberate treatment isolation, not removal of the atomic production primitives.

## Frozen matrix

Order is preregistered and never adaptively reordered:

1. click_commit r1
2. fill_submit r1
3. delayed_wait r1
4. delayed_wait r2
5. fill_submit r2
6. click_commit r2

The three user prompt templates and loopback fixture are byte/sha compatible with the prior v0.5/FC1 matrix. Each row uses a fresh LFL session, data directory, isolated Chrome profile and Browser action journal. Runs are strictly serial against the single already-running Ornith server on 8901.

## Runtime contract

- local model: `cognilocal/ornith-1.5-35b-a3b-mlx`
- Thinking: ON
- temperature: 0
- input/output contract: 184000 / 16000 tokens
- prompt concurrency: 1
- decode concurrency: 1
- max Agent rounds: 12
- per-row worker timeout: 240 s
- `EVIDENCE_MODE=enforce`
- no model fallback
- Method reflection / Summary / Extract / MCP / SMX: off
- isolated Chrome: mock keychain + basic password store; no SecurityAgent spawn allowed

## Frozen PASS gate

All conditions are conjunctive:

- 6/6 rows mechanically complete; no `TIMEOUT`, `INFRA_FAIL`, or `INVALID`;
- exact intended 3-tool provider surface on every row;
- no fallback and no SecurityAgent spawn;
- `browser_semantic_operation` adopted in 6/6 rows;
- external loopback task oracle 6/6, and each task 2/2;
- each row has at least one physical `navigate` ActionReceipt `ok`;
- click_commit/delayed_wait each have >=1 object mutation `ok`; fill_submit has >=2;
- each delayed_wait row has >=1 bounded-operation wait clause with `predicate_result=satisfied` before the successful click trajectory;
- every row has >=1 operation receipt ending `execution_status=clauses_exhausted`;
- zero operation tool FAILURE/ERROR, zero operation `halted`, zero unparsed operation receipts;
- every parsed operation receipt says `task_completion=not_evaluated`;
- zero automatic mutation retry at both operation and ActionReceipt layers;
- zero old scope/version blockers;
- zero direct model calls to hidden atomic Browser tools.

Call count, token count, get_tool_schema/read_evidence use, and number of operation invocations are diagnostics only; the program does not impose a semantic optimum.

## Evidence discipline

The gate, plan, source hashes, exact provider surface and runtime identity are frozen before the first measured model request. After measured execution begins:

- no row is selectively replayed;
- no failed row is repaired in-place;
- no Gate clause is weakened;
- timeout rows stay timeout rows;
- partial logs may explain a failure but cannot be promoted into terminal aggregates;
- failure closes this protocol as `NOT_QUALIFIED_BY_FC2B_V0.1`; any code/interface change requires a new protocol identity and fresh full matrix.

PASS does not authorize cloud canaries, fuzzy grounding, best-match ranking, auto-target/latest/rebind/retry, program-side task completion, or expansion of Browser permissions.
