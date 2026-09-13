# Browser Semantic Execute + Mechanically Typed Wait A2 — Main Matrix Qualification v0.6

## Question

在**不修改 production**、不改变 v0.5 任务输入/页面/oracle/runtime 的前提下，v0.6-A.1 已资格化的 mechanically typed wait + 既有 `browser_semantic_execute`，能否把 v0.5 的三项 Browser 主任务从不稳定的 1/2 提升为可重复的 2/2？

本轮只允许一个实验变量：模型工具面从 v0.5 的 `browser_perceive + browser_semantic_execute + get_tool_schema`，替换为当前 production 的 typed read-only waits + `browser_semantic_execute`。不改 universal prompt、Method、navigation interface、mutation compiler、任务 prompt、fixture、oracle、round budget 或 timeout。

## Frozen causal identity

A2 runner 在任何模型请求前必须硬校验：

- v0.5 plan array SHA256：`490c1e2cd1b9377468eb07dc06d05b8950faf10db4b61748ff89af1005b8f878`；
- v0.5 fixture byte SHA256：`87696076cea84d4e93f172d07a1499755dbc647f396ff115a9d64571740b72a3`；
- prompt template SHA256：
  - `click_commit`: `823e7cb25a1f2f234412564a93ed221956bdbcb4214aff1d67a78fd9296c6f2d`
  - `fill_submit`: `d80607ace4193874d8b7deddc2988f8b6562443b99b54455e48163cc4a6ff9e2`
  - `delayed_wait`: `eb99aac9458104ca12770d07ce1886f9d3bd76f8955ce9b5135de33b476ae694`

任何一项漂移都必须在 measured request 前拒绝执行。

## Frozen model surface

Exactly eight tools:

- `browser_perceive`
- `browser_wait_scope_url`
- `browser_wait_scope_ready`
- `browser_wait_scope_count`
- `browser_wait_object_state`
- `browser_wait_object_text`
- `browser_semantic_execute`
- `get_tool_schema`

Preflight 必须同时证明：

- `browser_perceive.action = snapshot|hydrate|diff`，无 `predicate`；
- `browser_semantic_execute` 仍只有 `verb + target_ref + args` 三字段，并保留 exact GroundingRef/resource_ref FCR 合同；
- five typed waits 的 required fields 与 v0.6-A.1 committed contract 完全一致；
- ready-state 是 closed enum；object-state `value` 是 JSON boolean；scope-count 是 integer>=0；interval_ms 1..5000；
- live 未支持的 `visible` 不进入 object-state enum；
- old generic `browser_wait_scope/browser_wait_object` 不在 surface。

## Model/runtime freeze

与 v0.5 完全相同：

- model: `cognilocal/ornith-1.5-35b-a3b-mlx`
- Thinking ON / reasoning effort medium
- temperature 0 / top_p 1 / top_k 0 / min_p 0
- max input 184000 / max output 16000
- max iterations 12
- worker timeout 240s
- no model fallback
- lazy tool schema ON
- fresh session, DATA_DIR, Chrome profile and fixture for every row
- exact isolated Chrome target; mock/basic keychain flags
- strict serial rows; one 8901 server, prompt/decode concurrency=1
- no row replay after failure/timeout

## Frozen matrix

Exact v0.5 symmetric order, seed `2026091311`:

1. `click_commit` repeat 1
2. `fill_submit` repeat 1
3. `delayed_wait` repeat 1
4. `delayed_wait` repeat 2
5. `fill_submit` repeat 2
6. `click_commit` repeat 2

Prompts, fixtures and external oracles are unchanged from v0.5.

## Pre-registered A2 gate

PASS only if all are true:

- 6/6 rows mechanically complete: no `TIMEOUT`, `INFRA_FAIL`, or `INVALID`;
- exact intended provider surface 6/6; no fallback; no SecurityAgent spawn;
- semantic mutation adoption 6/6;
- external task oracle PASS 6/6, therefore each task is 2/2;
- each row has at least one navigate `ok` receipt;
- each click/delayed row has at least one object `ok`; each fill row has at least two object `ok` receipts (fill + save click);
- **typed wait tool failures total = 0**;
- **old generic wait calls total = 0**;
- **legacy `browser_perceive(action=wait)` calls total = 0**;
- **`browser_perceive(snapshot,predicate=...)` calls total = 0**;
- old scope/version blocker receipts total = 0;
- automatic retry total = 0.

A row is **not required to call wait** when the semantic task does not need temporal observation. The gate tests wait correctness, not artificial wait adoption.

Observed but not added to the gate after execution begins:

- initial/non-GroundingRef `target_ref` failures;
- rounds / tool calls / input-output-cache tokens / wall time;
- `get_tool_schema` use;
- typed wait call count and satisfied/indeterminate details when no tool failure occurs;
- rejected receipts unrelated to the frozen old scope/version blocker class.

## Consequence

- A2 PASS: current local semantic-execute + mechanically typed wait surface is qualified on this six-row main matrix. This does **not** automatically launch cloud canary, navigation redesign, or bounded Semantic Operation.
- A2 FAIL: record `NOT_QUALIFIED_BY_A2`, do not replay rows, do not repair gate in-place, and do not change production inside this evidence set.
