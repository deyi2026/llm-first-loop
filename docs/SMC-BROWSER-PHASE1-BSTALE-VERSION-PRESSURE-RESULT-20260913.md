# SMC Browser Phase 1 — B-STALE / VERSION-PRESSURE Result (2026-09-13)

## 0. Verdict

**PASS — B-STALE / VERSION-PRESSURE 已具备独立收口资格。**

本阶段只完成 Browser 的机械版本前置条件与 retention/version-pressure 事实层；**没有**开放 mutation dispatch、ActionReceipt、click/fill/select/navigate/scroll/script，也没有新增 model-facing Browser verb。

Baseline:

```text
234bfce44958a5b74913d6fa82dc346d89cfcfee
```

Implementation commit:

```text
d83e9e09843fe27fded38bc2c2617a3e181d7d5b
feat(smc): add Browser version pressure guard
```

## 1. 核心裁决

### 1.1 不存在“自动 latest”

版本判断使用调用方显式提供的两份已持久化 observation：

```text
expected_version + observed_version + version_scope
```

kernel 不会：

- capture 一个“最新页面”；
- 自动 refresh；
- 自动 retry；
- silent rebind target；
- 按 name/role 猜一个替代对象；
- 判断哪个版本对任务“更好”。

因此这里的 `stale` 只表示：**相对于调用方明确给出的 observed_version，expected_version 不再满足指定机械 version_scope 的前置条件。**

### 1.2 pressure != stale

`pressure.present=true` 仅表示 expected / observed 都可用且 observation identity 不同。

它不自动意味着 stale：

- object scope：目标对象机械事实没变 → `match`；
- resource scope：page/document resource 事实没变 → `match`；
- snapshot scope：不同 snapshot identity → `stale`。

所以 version pressure 是事实，不是策略裁决。

### 1.3 stale != unavailable

一份 retained historical snapshot 可以同时满足：

```text
相对新 observation: stale
historical grounding: available
historical diff: usable
```

stale 不会删除历史证据，也不会自动刷新 GroundingRef。

## 2. Closed runtime result

内部 runtime primitive：

```text
BrowserPerceptionAdapter.assess_version_precondition(...)
```

它不进入 `BrowserPerceiveTool` model-facing surface。

结果固定字段：

```text
schema = smc.browser_version_assessment.v0.1
domain = browser
version_scope
scope_ref
target_id
expected_version
observed_version
expected_availability
observed_availability
result
reason
comparable
pressure
automatic_refresh_performed
silent_rebind_performed
```

`result`：

```text
match | stale | indeterminate
```

Grounding / snapshot availability 继续复用冻结 B-SPEC vocabulary：

```text
available | expired | unavailable | unauthorized
```

所有结果均明确：

```text
automatic_refresh_performed = false
silent_rebind_performed = false
```

## 3. version_scope 机械语义

### snapshot

- exact same snapshot → `match / exact_version`；
- same generation 下不同 observation identity → `stale / different_snapshot_same_generation`；
- generation 改代 → `stale` + `comparable=false`。

### object

- 只允许有稳定 identity basis 的 Semantic ID；
- snapshot-local AX identity → `indeterminate / target_identity_unstable`；
- 同 generation、同 Semantic ID、对象 mechanical semantic fields 未变 → `match / object_unchanged_new_observation`；
- 对象自身 fields 改变 → `stale / object_changed_same_generation`；
- complete observation 下对象消失 → `stale / target_absent_in_observed_version`；
- incomplete observation 下对象没看到 → `indeterminate / target_not_observed_incomplete`；
- 不按 same-name 新对象重绑。

### resource

- page lineage / document generation 是硬机械边界；
- 同 generation 下 document resource facts 未变 → `match / resource_unchanged_new_observation`；
- resource facts 改变 → `stale / resource_changed_same_generation`；
- document generation 改代 → `stale / document_generation_changed` + `comparable=false`。

## 4. Retention / eviction / unknown

Store inspection 只读取 exact persisted snapshot 与 declared retention：

- retained → `available`；
- TTL 越界 → `expired`；
- backing snapshot 不存在/被移除 → `unavailable`；
- session fence 不匹配 → `unauthorized`。

这些情况不会触发 recapture。expired/unavailable/unauthorized 的 version assessment 为 `indeterminate`，而不是伪装成 stale 或 fresh。

`pressure` 同时暴露：

```text
expected_expires_at_epoch
observed_expires_at_epoch
expected_seconds_until_expiry
observed_seconds_until_expiry
```

这属于 retention pressure 机械事实，不是模型该不该刷新证据的策略。

## 5. TDD / adversarial coverage

VersionPressure unit：**14 / 14 PASS**，覆盖：

- exact match；
- pressure 但 object 不变；
- object 自身变化；
- snapshot strict scope；
- resource unchanged / changed；
- full reload / document generation change；
- incomplete target absence；
- expired；
- unknown / unauthorized；
- physical backing snapshot removal → unavailable；
- snapshot-local AX unstable identity；
- invalid version_scope reject；
- model-facing Browser surface 不扩张。

此外 Predicate/wait、SemanticDiff、Perception、B-SPEC、contract、schema-lazy 与 live-navigation/perception expanded adjacency 全绿。

## 6. Real live qualification

环境：isolated Chrome + mock keychain/basic password store；外部 qualification controller 只修改隔离浏览器，production Browser host 保持 read-only。

Committed-state result：

```text
behavior: 13 / 13 PASS
safety:    6 / 6 PASS
total:    19 / 19 PASS
```

行为检查：

| Check | Result |
|---|---|
| exact version matches | PASS |
| pressure does not make unchanged object stale | PASS |
| pressure does not make unchanged resource stale | PASS |
| snapshot scope is strict across observations | PASS |
| same-document target change becomes stale | PASS |
| stable identity survives same-document churn | PASS |
| stale history remains hydratable | PASS |
| stale history remains diffable | PASS |
| reload generation is stale + incomparable | PASS |
| same-name reload object is not rebound | PASS |
| resource scope observes generation pressure | PASS |
| old Predicate scope after reload is indeterminate | PASS |
| version assessment never auto-refreshes | PASS |

安全检查：

| Check | Result |
|---|---|
| mock keychain enabled | PASS |
| basic password store enabled | PASS |
| security agent not spawned | PASS |
| production host exact-target bound | PASS |
| model surface unchanged/read-only | PASS |
| no mutation or ActionReceipt surface | PASS |

Formal committed-state live result SHA256:

```text
51268ff3b5b9e31a92a167425a18746e01310749fa4b3b0f3c19dd2613d2d2ae
```

## 7. Implementation hashes

```text
67364d82ac4cd92225d562f8940c064d8b23fda21a1bec4ef191ae00487dafee  scripts/qualification/smc_browser_live_version_pressure.py
c917bafdd8c0da54d02855e3ad5677764adf16bf8aaa9744aa1fb43f4e068d90  src/llm_loop/browser/perception.py
2d448315e6ca156f9800b28e1b5e551363dbc240b938c1b2d9bb5e27673911aa  tests/unit/test_smc_browser_version_pressure_v01.py
```

## 8. Gates before result-doc commit

```text
VersionPressure unit:               14 / 14 PASS
expanded Browser/SMC adjacency:    PASS
Ruff:                               PASS
py_compile:                         PASS
diff-check:                         PASS
whole-tree security:                1655 files PASS
full ci_gate:                       PASS
```

`ci_gate` 覆盖 Ruff + env-pin + Pyright + tier0 + full xdist。

### 8.1 Result-doc committed-state verification

包含本结果 MD/JSON 的 committed candidate：

```text
74009656f719e75bdd19b96b2972ab99101f3a45
```

提交态重新执行：

```text
live qualification:                 19 / 19 PASS
expanded Browser/SMC adjacency:     PASS
whole-tree security:                1659 files PASS
full ci_gate:                       PASS
live result SHA256:                 51268ff3b5b9e31a92a167425a18746e01310749fa4b3b0f3c19dd2613d2d2ae
```

因此本报告中的实现、证据 hash 与阶段边界已经经过包含报告本身的 committed-state 复验。

## 9. 明确未声称

```text
mutation dispatch:                  NOT_STARTED
ActionReceipt:                      NOT_STARTED
model-facing version-guard verb:    NOT_EXPOSED
silent refresh/retry/rebind:        FALSE
semantic freshness / task value:    NOT_JUDGED
"latest is best":                  NOT_JUDGED
capacity-based automatic GC policy: NOT_IMPLEMENTED / NOT_QUALIFIED
event-driven pressure feed:         NOT_QUALIFIED
```

本阶段只证明：**当模型/未来 dispatch 层明确给出 expected 与 observed observation 时，kernel 能诚实、scope-sensitive 地回答机械版本前置条件，并保留 retention/availability/pressure 事实。**

## 10. Phase boundary

B-STALE / VERSION-PRESSURE 到此停止。

下一阶段如果继续，才进入 mutation dispatch / ActionReceipt；本结果不能被引用成“Browser 已可安全写页面”。
