# SMC Browser Phase 1 — B-LIVE-SEMDIFF Result

Date: 2026-09-13
Status: **PASS**

## 1. Qualification boundary

本阶段只完成 **live SemanticDiff**。

正式模型面从：

```text
browser_perceive(snapshot | hydrate)
```

扩展为：

```text
browser_perceive(snapshot | hydrate | diff)
```

其中 `diff` 只接受两张已经落盘的 exact Browser snapshot：

```text
from_version
to_version
```

它不会：

- 重抓当前页面；
- 按 name / role / 文本相似度猜对象对应关系；
- 导航、点击、输入、滚动或执行脚本；
- 判断变化是否“重要”或是否与任务相关；
- 判断任务是否完成。

因此本阶段仍保持：

> 程序负责机械世界差异；模型负责解释差异的意义。

## 2. Source identity

基线：

```text
97f1c2a3f9227c4f38ec056ba27d6cdc3d174ade
```

Production SemanticDiff implementation：

```text
160b73d2b31f44c11510124feeac897db48fd6aa
feat(smc): add live Browser semantic diff
```

Qualification-only truncation follow-up：

```text
65dcdb2e4f8166c0c51471e86a9d5159903ff604
test(smc): cover truncated live Browser diff
```

最终资格 tip 为 `65dcdb2e...`；第二个提交只增强 qualification harness，不修改 production Browser diff 逻辑。

### File hashes

| File | SHA-256 |
|---|---|
| `scripts/qualification/smc_browser_live_semantic_diff.py` | `dbad23359b7960f79a2a8ab9204fad35588b5bf7c3103dcfdac99c4617d6cd04` |
| `src/llm_loop/browser/perception.py` | `bb74a1134bf286c493af93b25e449adcad24dc6abc462c02e7578027f2506d5a` |
| `src/llm_loop/tools/builtin/browser_perceive.py` | `22ad3c4e6ccee82706d3a93698dc3c2cdf52c07fac306e915f1464e70e1c47f2` |
| `tests/unit/test_smc_browser_perception_v01.py` | `81b1c1ac24974f7c6104ac6df5810685870e3bcbacf906f24413c7ec0d9c10d9` |
| `tests/unit/test_smc_browser_semantic_diff_v01.py` | `aecf792498a2114114967619917005786ff01ff6554b98910f6b131d8ee30de7` |

## 3. Implemented mechanical semantics

### 3.1 Exact snapshot pair only

`diff(from_version, to_version)` 从 `BrowserPerceptionStore` 精确加载两张 immutable snapshot。

读取受以下边界保护：

- snapshot id 格式验证；
- session owner fence；
- TTL；
- bundle integrity hash。

计算 diff 时不调用 Browser backend，因此不会把“比较历史状态”偷偷变成“重新观察当前状态”。

### 3.2 Canonical object change basis

对象变化只比较 SMC Browser 已声明的机械语义字段：

```text
scope_ref
kind
attributes
state
relations
coverage
```

明确排除每次 snapshot 天生变化的：

```text
grounding_ref
observed_version
```

因此历史引用本身不会制造假 `changed`。

relations/list facts 在比较前做 canonical ordering，避免观察顺序差异制造噪声。

### 3.3 Created / removed / changed

同一可比 scope 内：

- `created` / `removed` 基于机械稳定 Semantic ID；
- `changed` 只在同一稳定 Semantic ID 的交集上比较字段；
- replacement 即使 name/role 一样，也不会被自动重绑。

字段变化使用细粒度事实，例如：

```text
state.enabled
attributes.<field>
relations
coverage.<field>
```

### 3.4 Snapshot-local AX identity

真实 Chrome 暴露了一个 deterministic fixture 没充分体现的事实：同一物理 UI 周围可能同时存在：

```text
dom_physical_identity
ax_backend_physical_identity
snapshot_local_ax_identity
```

`snapshot_local_ax_identity` 只对当前 observation 有效；下一张 snapshot 生成新的局部 ID。

如果直接做 ID 集合差，会把不变页面误报为：

```text
removed old-local-id
created new-local-id
```

本阶段最终裁决是：

- **不**按 name / role / text 自动匹配这些局部 card；
- snapshot-local IDs 不进入 world-level created/removed/changed；
- diff 显式写入 `identity_unstable_objects`；
- `completeness.complete=false`；
- `field_completeness.created/removed/changed=false`；
- 具有稳定 physical identity 的差异仍可作为机械 lower-bound 保留。

这同时避免了“假 churn”和“程序偷偷猜身份”。

### 3.5 Incomplete observation

若任一侧 snapshot 本身不完整，例如 sensor truncation：

```text
created = null
removed = null
```

不能用 partial set 猜“没有看见 = 被删除”。

`changed` 只允许保留稳定 ID 交集上真实观察到的 lower-bound；field completeness 必须为 false。

### 3.6 Scope comparability

以下情况不能直接解释为同一对象集合的普通 diff：

- full document generation 改代；
- 同一 frame identity 的 document generation 改代；
- scope 不明；
- sensor contract 不一致。

full reload / frame navigation 的结果为：

```text
comparable = false
scope_relation = changed
created = null
removed = null
changed = null
```

因此不会把导航后的新页面伪装成“大量删除 + 大量新增”。

## 4. Canonical diff grounding

每个 diff 有 immutable `full_list_ref`：

```text
grounding://browser/v0.1/<to_snapshot>/diff/<from_snapshot>
```

Canonical diff grounding：

- session fenced；
- integrity hashed；
- retention 不超过两张 source snapshot 的最短有效期；
- 同一 snapshot pair 重复 diff 为幂等读取；
- 文件被篡改后 hydrate 明确返回 integrity error；
- 不重新计算、不重抓当前世界、不 silent rebind。

## 5. Formal live qualification

环境：

```text
Google Chrome 152.0.7977.84
--use-mock-keychain
--password-store=basic
```

Production `CdpReadOnlyBrowserHost` 始终只读。世界变化由 qualification-only 独立 control plane 制造；该 control plane 不在 `src/llm_loop` production import graph 中。

Formal result：

```text
status: PASS
behavior: 15 / 15 PASS
safety:    5 / 5 PASS
total:    20 / 20 PASS
```

Formal result SHA-256：

```text
b0af595c5c392de494b243127f9ca60ae57624fd9f19a2dd04370680dd475915
```

### Behavior checks

| Check | Result |
|---|---|
| same-document comparable | PASS |
| same-document scope same | PASS |
| stable physical identity preserved | PASS |
| stable field change observed | PASS |
| same-name replacement old removed | PASS |
| same-name replacement new created | PASS |
| replacement not name-rebound | PASS |
| same-document identity partial explicit | PASS |
| no-op net diff empty | PASS |
| no-op identity partial explicit | PASS |
| full_list_ref exact hydration | PASS |
| reload diff incomparable | PASS |
| reload does not mass-diff | PASS |
| truncated created/removed unknown | PASS |
| truncated field completeness false | PASS |

### Safety checks

| Check | Result |
|---|---|
| mock keychain enabled | PASS |
| basic password store enabled | PASS |
| SecurityAgent not spawned | PASS |
| production host exact-target bound | PASS |
| model surface has no mutation | PASS |

## 6. Test and repository qualification

实际执行：

```text
direct semantic-diff + perception: 57 / 57 PASS
expanded Browser/SMC adjacency:    148 / 148 PASS
```

Expanded adjacency 包含：

- B-LIVE-SEMDIFF；
- B-PERCEPTION；
- B-LIVE-PERCEPTION；
- B-LIVE-NAVIGATION；
- B-SPEC；
- SMC core；
- schema-lazy；
- factory；
- arch guards。

静态与仓库门：

```text
Ruff:        PASS
py_compile:  PASS
src Pyright: 0 errors / 0 warnings / 0 informations
env-pin:     540 test files / 0 violations
tier0:       PASS
full pytest: PASS
full ci_gate: exit 0
whole-tree security: 1650 files PASS
```

第一次 implementation 候选 full gate 中 `test_job_registry.py` 曾出现一次 xdist 分布假红；仓库既定 D-B2-09 serial 复核为绿，因此该 gate 按既定政策 PASS。qualification follow-up 的下一次 full gate 中 xdist 直接全绿。该测试文件未被本阶段修改。

## 7. What this stage proves

本阶段可以正式写成：

> **Browser Phase 1 的 live SemanticDiff 已通过 deterministic + real Chrome qualification。程序可以在不重抓当前世界、不猜测语义身份的前提下，对 exact snapshots 给出 scope-aware、completeness-aware、可 hydration 的机械差异。**

它尤其证明了：

1. 同文档 stable identity 的字段变化可被机械识别；
2. 同名 replacement 不会 alias；
3. snapshot-local AX identity 不会再制造假 world churn；
4. 不完整 observation 不会制造确定性 created/removed；
5. full reload / frame navigation 不会被伪装成普通对象集合差；
6. canonical diff 可持久化、校验并精确 hydrate。

## 8. What this stage does NOT prove

以下全部仍未开始或未资格：

```text
Predicate / wait:              NOT_STARTED
staleness / version pressure:  NOT_STARTED
mutation dispatch:             NOT_STARTED
ActionReceipt:                 NOT_STARTED
cross-URL Page.navigate:       NOT_QUALIFIED
vision Phase 2:                DEFERRED
```

因此不得将本报告摘引为：

- “Browser Agent 已完成”；
- “Browser mutation 已通过”；
- “wait/predicate 已可用”；
- “页面变化的重要性由程序判断”；
- “所有 AX card 都有稳定跨 snapshot identity”。

## 9. Next gate

按既定顺序，下一阶段应为：

```text
B-PREDICATE / WAIT
```

进入该阶段前，本阶段必须保持独立收口；不得因为 SemanticDiff PASS 就自动开放 mutation。
