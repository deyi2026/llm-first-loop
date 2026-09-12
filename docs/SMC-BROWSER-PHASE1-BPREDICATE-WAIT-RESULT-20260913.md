# SMC Browser Phase 1 — B-PREDICATE / WAIT Result

Date: 2026-09-13
Status: **PASS**

## 1. Qualification boundary

本阶段只完成 **structured Predicate + read-only polling wait**。

模型面由：

```text
browser_perceive(snapshot | hydrate | diff)
```

扩展为：

```text
browser_perceive(snapshot | hydrate | diff | wait)
```

`Predicate` 是 closed typed data object，不是自然语言判断入口。`wait` 只做 observation polling，不点击、不输入、不导航、不滚动、不执行模型脚本，也不判断任务是否完成。

本阶段刻意没有开放：

```text
assert
staleness / version pressure
mutation dispatch
ActionReceipt
```

因此保持原裁决：**程序负责机械验证与等待，模型负责声明要验证的条件、解释结果并决定下一步。**

## 2. Source identity

基线：

```text
93182e1b356b049e604f60627799df766d28257f
```

实现提交：

```text
aecf93aedb2babea3b7db48e3cf60cf8e8be6511
feat(smc): add Browser predicate wait
```

### File hashes

| File | SHA-256 |
|---|---|
| `scripts/qualification/smc_browser_live_predicate_wait.py` | `c00647311b7fe8266d0a7f2a577e002ba00b88c8e4b3ab5c97717c5852ebdfe2` |
| `src/llm_loop/browser/predicate.py` | `44a1e395ac869d464e95584335de7fd362d80e0ede852faa13b7557855007343` |
| `src/llm_loop/browser/perception.py` | `93610bd87d2e8db964a53cf9b095acf404e4c40e2e1f37fcf67ace007d281c7d` |
| `src/llm_loop/tools/builtin/browser_perceive.py` | `587976b55c1ac6dc50e60cf13ceb211f9f2264d53f97d3ca27eedbe79f9f9d29` |
| `tests/unit/test_smc_browser_predicate_wait_v01.py` | `2fe398de058666c04b837bbfd927e3ceb06b9ca854cffe78c35792a70e6f701b` |
| `tests/unit/test_smc_browser_perception_v01.py` | `03070ef64551ba0fdd1b216ff2bc7a4b5e9aac31c1c766e29776c2e6fbb25b7a` |
| `tests/unit/test_smc_browser_semantic_diff_v01.py` | `6b05e1cff78a2fb72f50e1b6c59769aaf2f88bc49002175c96c83050d8f66557` |

## 3. Predicate contract implemented

运行时 vocabulary 与冻结 B-SPEC profile 做机器 parity，支持：

```text
exists
enabled
visible
checked
selected
expanded
focused
editable
url
name
value_text
document_ready_state
object_count
```

每个 property 的 operator/value type/value enum 都来自 closed contract。以下输入会在 capture 前机械拒绝：

- 未知 property；
- 不允许的 operator；
- 错误 value type；
- 额外字段；
- 非 Browser domain/schema；
- object predicate 使用非 SemanticObject ID；
- scope predicate 的 target 不等于 exact `scope_ref`。

程序不会猜测模型真正想表达什么。

### 3.1 三态不是二态包装

Predicate evaluation 为：

```text
satisfied
unsatisfied
indeterminate
```

`indeterminate` 用于“事实无法机械判定”，不是普通 false。

例如：

- 属性没有被当前 sensor 观测 → `indeterminate/property_unobserved`；
- predicate scope 当前没有被观测 → `indeterminate/scope_not_observed`；
- target Semantic ID 未知或只有 snapshot-local identity → `indeterminate`；
- 证明对象不存在但 coverage 不完整 → `indeterminate`。

### 3.2 否定需要 coverage

对稳定 Semantic ID 的 `exists == false`，只有同时满足：

1. 该 ID 曾由当前 runtime 机械证明为稳定 identity；
2. target 绑定的 exact scope 与 predicate scope 一致；
3. 当前 observation 对该 scope 足够完整；
4. 当前对象集合中确实没有该 ID；

才可返回 `satisfied`。

因此“没看到”不会被自动升级成“对象不存在”。

snapshot-local AX ID 或凭空构造的 `el_...` 也不会被当成可证明的旧对象身份。

### 3.3 Partial coverage lower-bound

`object_count` 在 incomplete observation 下不伪造 exhaustive count：

- 已观察 lower bound 已足够证明 `ge` → 可以 `satisfied`；
- lower bound 已超过 `eq/le` 上界 → 可以 `unsatisfied`；
- 其它情况 → `indeterminate`。

程序只使用机械 lower-bound，不补全未观测世界。

### 3.4 Scope-level facts

`url` 和可选 `document_ready_state` 绑定到 exact opaque scope_ref，并进入 snapshot content grounding identity。

当前 production `CdpReadOnlyBrowserHost` 仍只允许既有四个只读 CDP 方法，没有加入 `Runtime.evaluate`。因此：

- `url` 当前可机械观测；
- `document_ready_state` 属于合法 Predicate property，但当前 live sensor 不提供该事实，结果如实为 `indeterminate`。

这不是用程序伪造默认值，也不会为了“全支持”扩大 production CDP 权限。

## 4. Wait semantics implemented

`wait` 参数：

```text
predicate
timeout_ms
interval_ms
```

当前资格只覆盖 `evaluation_mode=polling`。

每个 polling sample：

```text
read-only capture
→ immutable WorldSnapshot
→ Predicate evaluation
```

sample 是 observation，不是 action retry。

### 4.1 Timeout is fact, not tool failure

若 deadline 前有效采样始终没有满足 Predicate：

```text
ToolResult.status = success
predicate_result.result = unsatisfied
```

若关键观测不可得：

```text
ToolResult.status = success
predicate_result.result = indeterminate
```

不会把 timeout 自动解释为“换 target / 换策略 / 重试动作”。

### 4.2 Observer errors stay visible

Polling 暴露：

```text
interval_ms
sample_count
observer_error_count
observed_at
deadline
```

一次 observer error 后若后来取得充分有效观察，可以按有效观察得到 `satisfied`，但 `observer_error_count` 不会被抹掉。

如果只有 observer failures，则最终为 `indeterminate`，而不是谎报 `unsatisfied`。

### 4.3 No silent parameter correction

`timeout_ms` / `interval_ms` 超过硬边界时直接拒绝，不 silent clamp。当前硬边界：

```text
timeout_ms:  1..60000
interval_ms: 1..5000
```

## 5. No ActionReceipt claim

本阶段 wait 返回的是 read-only observation envelope：

```text
action
predicate
predicate_result
observation
```

明确没有：

```text
action_id
receipt_id
receipt_seq
before_version
after_version
```

Predicate observation 绑定 exact `snapshot_id`；canonical ActionReceipt/receipt grounding 留到既定后续阶段实现。因此不得把当前 wait envelope 宣称为 ActionReceipt。

## 6. Formal live qualification

环境：

```text
Google Chrome 152.0.7977.84
--use-mock-keychain
--password-store=basic
```

世界变化仅由 qualification-only control plane 制造；production `CdpReadOnlyBrowserHost` 始终走只读 capture surface。

Formal result：

```text
status:   PASS
behavior: 9 / 9 PASS
safety:   6 / 6 PASS
total:   15 / 15 PASS
```

Formal result SHA-256：

```text
b613a90a67c355f36230217dcc9d9dd8c999fcc2e4e8604c7e35c839d78ce3dd
```

### Behavior checks

| Check | Result |
|---|---|
| live disabled→enabled transition satisfied | PASS |
| stable Semantic ID preserved across wait | PASS |
| complete coverage proves live absence | PASS |
| impossible condition timeout is unsatisfied observation | PASS |
| unobserved ready-state is indeterminate | PASS |
| partial coverage object-count is indeterminate | PASS |
| observer error then valid sample recovers | PASS |
| PredicateResult sampling facts visible | PASS |
| wait has no ActionReceipt fields | PASS |

### Safety checks

| Check | Result |
|---|---|
| mock keychain enabled | PASS |
| basic password store enabled | PASS |
| SecurityAgent not spawned | PASS |
| production host exact-target bound | PASS |
| model surface has no mutation | PASS |
| `assert` not exposed in this stage | PASS |

## 7. Test and repository qualification

实际执行：

```text
direct Predicate/wait tests:       18 / 18 PASS
expanded Browser/SMC adjacency:   133 / 133 PASS
```

Expanded adjacency 包含 Browser live navigation/perception、perception、SemanticDiff、B-SPEC、SMC contract 与 schema-lazy。

静态与仓库门：

```text
Ruff:        PASS
py_compile:  PASS
src Pyright: 0 errors / 0 warnings / 0 informations
env-pin:     541 test files / 0 violations
tier0:       PASS
full pytest: PASS
full ci_gate: exit 0
whole-tree security before result docs: 1653 files PASS
whole-tree security final candidate: 1655 files PASS
```

## 8. What this stage proves

本阶段可以正式写成：

> **Browser Phase 1 已具备 closed typed Predicate 与 read-only polling wait：模型声明机械条件，程序在 exact scope/observation 上验证并返回诚实三态；timeout、observer error、coverage 缺口都作为事实暴露，而不是触发隐藏策略或动作重试。**

尤其证明：

1. stable object 状态变化可被 live wait 等到；
2. 完整 coverage 可机械证明稳定对象已消失；
3. 不完整 coverage 不会制造否定结论；
4. observer error 不会被静默吞掉；
5. 当前 sensor 未观测 ready-state 时不会伪造结果；
6. wait 没有 mutation、没有任务完成判断、没有 ActionReceipt 冒名。

## 9. What this stage does NOT prove

以下仍未开始或未资格：

```text
assert model action:              NOT_EXPOSED_THIS_STAGE
event-driven wait:                NOT_QUALIFIED
staleness / version pressure:     NOT_STARTED
mutation dispatch:                NOT_STARTED
ActionReceipt:                    NOT_STARTED
cross-URL Page.navigate:          NOT_QUALIFIED
vision Phase 2:                   DEFERRED
```

因此不得将本报告摘引为“Browser mutation 已完成”“版本压力已解决”或“wait 成功代表任务完成”。

## 10. Next gate

按既定顺序，下一阶段才是：

```text
B-STALE / VERSION-PRESSURE
```

本阶段应先独立收口；不得因为 Predicate/wait PASS 就自动开放 mutation 或 ActionReceipt。
