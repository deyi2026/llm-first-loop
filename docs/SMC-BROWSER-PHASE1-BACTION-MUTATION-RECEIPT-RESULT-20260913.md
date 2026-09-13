# SMC Browser Phase 1 — B-ACTION Mutation Dispatch + ActionReceipt Result

Date: 2026-09-13
Baseline: `ba8bf6423e684448045297399f6f3111144077fe`
Implementation commit: `8135946a87e62e4ef73750839c5a80b8107e2e43`
Status: **QUALIFIED WITH EXPLICIT LIMITS**

## 1. 裁决

Browser Phase 1 的写操作最小闭环已经从纸面合同进入真实 runtime：

> 模型提交显式 SemanticAction → runtime 做机械 pre-dispatch observation/version/identity guard → 只允许 exact target 单次 dispatch → append-only ActionReceipt 记录 before/dispatch/after 可回验事实。

这不是“浏览器自动化成功判定器”。runtime 不判断任务是否完成、动作是否有语义价值、是否值得重试，也不自动找替代目标。

本阶段完成了 `click / fill / select / navigate / scroll(semantic_object)` 的真实 Chrome qualification，并保持以下硬边界：

- perception 与 mutation 权限分离；
- mutation 默认关闭；
- stale / indeterminate / target ambiguity 在 dispatch 前拒绝；
- 同一 `action_id` 永不二次 dispatch；
- transport/backend failure 不自动 replay；
- receipt revision append-only，不覆盖历史；
- `status=ok` 只表示机械 dispatch acknowledgement + 当前可观察事实，不表示 task completion；
- model-facing surface 不暴露 selector / XPath / coordinate / backend node id / arbitrary script / raw CDP method。

## 2. 生产实现

### 2.1 Action orchestration / receipt store

`src/llm_loop/browser/action.py`

- frozen mutate contract：`click / fill / select / navigate / scroll`
- all mutations: `operation_class=mutate`
- all mutations: `idempotency_class=unknown`
- all mutations: `atomicity_class=single_dispatch`
- `expected_version + version_scope + version_precondition=required`
- durable `action_id` reservation prevents duplicate dispatch
- pre-dispatch fresh read-only capture
- reuses `assess_version_precondition(...)`
- exact Semantic ID → private stable physical identity re-resolution
- exact current `scope_ref` check before object dispatch
- append-only `running → terminal` ActionReceipt revisions
- per-action monotonic `receipt_seq`
- process-level receipt lock + file lock
- post-dispatch observation/diff attempted even after dispatch ambiguity
- privacy-safe dispatch grounding with raw physical id/value omitted

### 2.2 Independent mutation actuator

`src/llm_loop/browser/cdp_action_host.py`

Existing `CdpReadOnlyBrowserHost` remains read-only and unchanged as the perception trust boundary.

The mutation actuator is a separate capability with a narrow hard allowlist:

- `DOM.resolveNode`
- `Runtime.callFunctionOn`
- `Page.navigate`

The model cannot provide CDP method names or JavaScript. Object mutations use fixed internal functions; user values are protocol arguments, not function source.

Target binding is exact. If the bound page disappears or websocket identity changes, the actuator fails instead of silently rebinding.

### 2.3 Model-facing tool and capability grant

`src/llm_loop/tools/builtin/browser_action.py`

A separate `browser_action` tool exposes the frozen `SemanticAction v0.1` fields.

Mutation is independently opt-in:

- setting: `browser_action_enabled: bool = False`
- env: `LFL_BROWSER_ACTION_ENABLED`
- Browser perception being enabled **does not grant write authority**

The factory registers `browser_action` only when Browser perception is configured and the independent write flag is true.

## 3. Pre-dispatch mechanical guard

The dispatch path is deliberately conservative:

1. validate the closed SemanticAction contract;
2. reserve `action_id` durably;
3. capture a fresh read-only Browser observation;
4. persist it as an observed snapshot;
5. compare `expected_version` against the observed version using the already-qualified B-STALE guard;
6. require result=`match`;
7. re-resolve the exact target in the observed snapshot;
8. require stable private identity and matching `scope_ref`;
9. persist privacy-safe dispatch grounding;
10. append `running` receipt;
11. dispatch exactly once;
12. attempt post-dispatch observation/diff;
13. append a new terminal receipt revision.

There is no automatic refresh strategy, best-match substitution, selector fallback, recovery loop, or semantic retry policy in this path.

## 4. ActionReceipt behavior

Canonical receipt fields remain closed and include:

- action and target identity
- `receipt_id / receipt_seq`
- operation/idempotency/atomicity classes
- `status = running | ok | failed | rejected`
- `before_version / after_version`
- observed effects refs
- boundary events
- grounding refs
- completeness
- predicate result slot
- explicit retry facts

`running` and terminal receipts are different immutable revisions for the same `action_id`.

Duplicate calls with the same `action_id` append a later `rejected` receipt but do not dispatch again.

`retry.automatic_retry_performed` remains `false` throughout v0.1.

## 5. Privacy and security boundaries

Persisted action evidence does not store raw fill/select values or full navigation URLs:

- fill text → length + SHA256
- select value → length + SHA256
- navigation URL → length + SHA256
- physical DOM target → SHA256 only

Navigation accepts only `http` / `https` with a hostname and rejects credential-bearing URLs plus `javascript:` / `file:` / `data:` and other schemes before capture/dispatch.

The live harness uses isolated Chrome with mock keychain/basic password store and verifies no new SecurityAgent process is spawned.

## 6. Real Chrome qualification

Harness:

`scripts/qualification/smc_browser_live_action_receipt.py`

Committed-state result SHA256:

`49b6c1620aaf4c225342e34e7424a16cc0bf0b24d00a4e8fb7f8a285bf6d933f`

### 6.1 Behavior — 15 / 15 PASS

| Check | Result |
|---|---|
| click single dispatch applied | PASS |
| duplicate action id rejected without second click | PASS |
| fill applied | PASS |
| select applied | PASS |
| semantic-object scroll applied | PASS |
| stale object rejected before click | PASS |
| same-name replacement never rebound | PASS |
| navigate single dispatch acknowledged | PASS |
| navigate reached exact loopback resource | PASS |
| receipt running → terminal append-only | PASS |
| receipt before/after versions present | PASS |
| dispatch grounding durable | PASS |
| automatic retry never performed | PASS |
| terminal status not task completion | PASS |
| boundary completeness not overclaimed | PASS |

### 6.2 Safety — 8 / 8 PASS

| Check | Result |
|---|---|
| mock keychain enabled | PASS |
| basic password store enabled | PASS |
| SecurityAgent not spawned | PASS |
| read host exact target bound | PASS |
| mutation actuator exact target bound | PASS |
| model surface has no physical locator/script inputs | PASS |
| fill plaintext absent from action store | PASS |
| dispatch grounding hides raw physical target | PASS |

## 7. Live qualification found a real implementation defect

The first real Chrome run produced only `10/15 behavior + 7/8 safety`.

Root cause was not the Semantic ID design or version guard. Live Browser perception already persisted private physical identity as:

`dom:<backendNodeId>`

The first actuator integration prefixed it again, producing:

`dom:dom:<backendNodeId>`

That caused object mutations to fail before real dispatch with `ValueError`.

The fix normalizes the physical target to exactly one `dom:` prefix. After that correction, click/fill/select/scroll all became real DOM effects while stale/replacement/duplicate/no-retry safeguards remained passing.

This failure is retained as useful evidence that the qualification exercised the real perception→grounding→actuator seam rather than only mocked happy paths.

## 8. Unit / adjacency / static / full repository verification

Committed implementation state:

- Browser/SMC focused suite: **135 / 135 PASS**
- Ruff `src tests scripts`: **0 violations**
- Pyright `src`: **0 errors / 0 warnings / 0 informations**
- env-pin gate: **544 files / 0 undeclared COMPACT_RATIO dependents**
- tier0: PASS
- full xdist suite: PASS
- architecture guard report: PASS
- whole-tree security scan: **1665 tracked files PASS**
- complete `scripts/ci_gate.sh`: **exit 0**

Implementation hashes:

| Artifact | SHA256 |
|---|---|
| `src/llm_loop/browser/action.py` | `38d7cb3134b89be31f659e80c3988e70d9bfd52d827b8bc455df2a3d2878c23b` |
| `src/llm_loop/browser/cdp_action_host.py` | `1cbb31b4e3b2dbcedd8865c2e06f19357cb3fe466834ccdf43d018c3698d0d90` |
| `src/llm_loop/tools/builtin/browser_action.py` | `d0425a5e528f1aa485cf49a47fa05dff72982d134243c794041df9927eeb7818` |
| live qualification harness | `014bdc1d8500402feee9ae324fbe9be751f27e20137811748b23b0168e1a234d` |

## 9. Explicitly NOT qualified / NOT claimed

The following are deliberately not promoted into claims for this stage:

1. **Root-level scroll targets are not qualified.**
   The frozen Profile lists `page / document / frame / region` in addition to `semantic_object` for `scroll`. This stage live-qualified `semantic_object` scroll only. Strict snapshot-version semantics from B-STALE must not be weakened merely to make root-scroll appear supported. Root-level scroll needs a separate contract clarification/qualification around semantic-root versioning.

2. **Live transport-ambiguity injection is not qualified.**
   Unit tests verify dispatch exception → exactly one attempt, no automatic retry, post-observation still attempted, receipt=`failed`/ambiguous. A real Chrome transport timeout after send was not injected in this stage.

3. **Boundary-event detection is not exhaustive.**
   Popup/new-window/download/dialog/permission events are not claimed as comprehensively detected. Receipt completeness therefore remains provisional/false when the detector cannot prove exhaustive coverage.

4. **No automatic retry / recovery policy.**
   v0.1 intentionally has none for unknown-idempotency mutations.

5. **No target fallback or selector recovery.**
   Same-name replacement is rejected, not rebound.

6. **No task-completion or semantic-success judgement.**
   `ok` is a mechanical acknowledgement/evidence state only.

7. **No vision/coordinate mutation path.**
   Phase 1 remains exact semantic-object/page grounding through the Browser structural sensors.

## 10. Phase result

B-ACTION establishes the minimum trustworthy Browser write loop:

> **explicit model action → mechanical authority/version/identity guard → one physical dispatch → durable append-only evidence**

Within the qualified surface, Browser SMC is no longer only a reliable perception layer; it now has a mechanically fenced actuator without introducing a second semantic decision system in runtime.
