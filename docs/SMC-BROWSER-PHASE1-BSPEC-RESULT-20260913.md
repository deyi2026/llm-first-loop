# SMC Browser Phase 1 B-SPEC Result — 2026-09-13

> Baseline: `5f19eb9457024b98f51dac02ed8ca6705e046b40`
> R3 authority: `docs/SMC-R3-BROWSER-PAPER-STRESS-20260913.md/json`
> Domain profile: `docs/SMC-BROWSER-PHASE1-PROFILE-v0.1.md/json`
> Closed wire schema: `docs/SMC-BROWSER-PHASE1-SCHEMA-v0.1.json`
> Nature: **spec/schema conformance only; Browser implementation not started**.

## 1. 裁决

B-SPEC 已把 Browser Phase 1 从“R3 纸面充分”推进到**可机械拒绝错误 wire 的 closed domain specification**。

当前最准确结论：

> **Browser Phase 1 的机械语言已冻结；Browser 世界尚未接入。**

因此本阶段：

- **Spec/profile conformance: PASS**
- **Closed wire schema conformance: PASS**
- **Authority negative tests: PASS**
- **Browser implementation conformance: NOT_TESTED**
- **30 个 R3 Phase 1 deterministic implementation fixtures: NOT_IMPLEMENTED / obligation frozen**
- **Phase 2 vision-only actionability: DEFERRED**
- **Phase 3 native browser chrome / OS UI: DEFERRED**

这不是 Browser 成熟度评分，也不授权把 legacy Playwright selector/script surface 当 SMC adapter。

## 2. 冻结工件

| 工件 | 用途 | SHA-256（pre-result freeze） |
|---|---|---|
| `SMC-BROWSER-PHASE1-PROFILE-v0.1.md` | 中文 Browser domain profile | `40673778e97103e5f7860d9dfe687bc5d3b445d8e7699a9e8d1094f9949f7934` |
| `SMC-BROWSER-PHASE1-PROFILE-v0.1.json` | machine profile / cross-field authority | `e7365fb48b3cc1b6fc5d0efc3e983c0e72f29d9686ade705f4a7242171220d0d` |
| `SMC-BROWSER-PHASE1-SCHEMA-v0.1.json` | Draft 2020-12 closed model-facing shape | `ba810509fbb31e91dc15e4a04982fdfdacff6bdc2e408606aa90ceeba961d83c` |
| `test_smc_browser_phase1_spec_v01.py` | deterministic conformance / adversarial lint | `c9244ee9be003f829f96d2e6a2fdf8a1b6e013132e20cb27d9495fd5d53a4ee6` |

这些 hash 记录的是结果报告生成前的冻结候选。若后续验证只修改本结果报告，不影响它们；若四个核心工件任一字节变化，必须重算并重新资格。

## 3. 为什么是 Profile + Schema 两层，而不是一份万能 JSON Schema

### Closed JSON Schema 负责形状

- 六类 canonical model-facing object；
- required/type/enum/const；
- 递归 `additionalProperties=false`；
- closed attributes/state/relations/coverage；
- closed action args；
- 不允许 selector/XPath/坐标/node id/AX index/hint/策略字段进入已知 wire。

### Machine Profile 负责交叉机械语义

- `verb → args_schema`；
- `verb → operation/idempotency/atomicity`；
- `verb → expected_version/version_scope`；
- `Predicate.property → operators/value type/value enum`；
- scope generation / sensor contract / C28；
- retry/receipt/grounding/boundary discipline；
- B0–B14 与 R3 fixture obligations。

这避免两个坏方向：

1. 为了“schema 能表达所有语义”把 schema 写成隐性策略引擎；
2. 只校 JSON 形状，却允许 `verb=click + navigate args + idempotent` 这种机械矛盾 wire 通过。

## 4. B-SPEC 的关键冻结裁决

### 4.1 Surface isolation

Browser qualification model surface 必须是 SMC-only。

`playwright_exec` / `playwright_test` 只保留为 backend/L1/E2E 资产；若未来实验臂模型直连 legacy tool，该 run 必须禁止或记 intervention。

### 4.2 Scope / identity

- scope hierarchy: `runtime → page → document → frame`；
- Semantic ID 唯一范围：runtime/session；
- navigation/frame navigation/restart 有显式 generation/invalidation；
- 相似性不是 identity proof；
- ambiguity 不得自动 best-match。

### 4.3 DOM + AX + C28

- active sensors = DOM + AX；
- vision = explicit-only / Phase 2 deferred；
- 无 silent sensor priority；
- unresolved multi-sensor canonical field = `null`；
- `coverage.conflicts` 保留 source/value/grounding；
- identity mapping ambiguity 不强融。

### 4.4 Predicate

自然语言 predicate 被关闭。第一版 property/operator/value type 全部 closed，结果统一：

```text
satisfied / unsatisfied / indeterminate
```

polling 仍必须暴露 interval/sample/error/time facts，不能把 sample miss 写成“期间从未发生”。

### 4.5 SemanticAction

第一版 verbs：

```text
observe hydrate diff wait assert click fill select navigate scroll
```

mutate verbs 全部要求 `expected_version + version_scope`；dispatch 前未来实现必须重新 resolve identity。

### 4.6 Retry

v0.1 明确：

```text
automatic_protocol_retry = disabled_v0.1
```

理由不是“重试永远错误”，而是 Phase 1 先冻结一次动作的机械含义。未来若开放，只能基于可审计机械幂等依据并升级 profile/version。

### 4.7 Receipt / grounding

- append-only；
- `receipt_seq` per action_id strictly monotonic；
- terminal 不覆盖 prior receipt；
- action status ≠ task completion；
- no silent recovery sequence；
- grounding 可用性：available/expired/unavailable/unauthorized；
- same GroundingRef 不重绑新状态。

## 5. TDD 证据

### RED #1 — 规格文件不存在

先写 conformance test，再执行：

```text
FileNotFoundError:
docs/SMC-BROWSER-PHASE1-PROFILE-v0.1.json
```

说明测试不是对既有文件“补截图式证明”，而是先冻结目标合同。

### GREEN #1

生成 Profile + Closed Schema 后：

```text
17 / 17 PASS
```

### RED #2 — retry contract 未显式冻结

加入 cross-field adversarial tests 后，exact top-level profile contract 要求 `retry_contract`，旧 profile 缺失而失败。

这个 RED 迫使第一版做出明确裁决：

```text
automatic_protocol_retry = disabled_v0.1
polling_samples_are_retries = false
model_explicit_repeat_uses_new_action_id = true
future_retry_requires_auditable_mechanical_idempotency_basis = true
```

### GREEN #2

补齐 retry contract、verb/Predicate cross-field negative tests 后：

```text
20 / 20 PASS
```

### 最终 machine-lint

最后增加：

- 所有 `$ref` 必须解析到真实 `$defs`；
- 所有 verb `args_schema` 必须存在；
- model-facing property name 不得出现 selector/策略/hint 等禁用名。

最终：

```text
21 / 21 PASS
```

## 6. 当前 adversarial coverage

当前测试已能机械拒绝：

- `recommended_action / priority / completion / best_candidate`；
- selector / XPath / x-y / CDP node id / AX index / native handle；
- locator 藏进 action args；
- 临场 `attributes.hint`；
- `verb=click` 配 navigate URL args；
- action operation/idempotency/atomicity 与 verb profile 不一致；
- mutate action 缺 expected_version；
- Predicate property/operator 不匹配；
- Predicate value type 不匹配；
- Predicate enum value 不合法；
- unknown object fields；
- dead `$ref` / dead args schema。

这些检查只裁机械协议，不判断“点哪个按钮更合适”。

## 7. R3 / B0–B14 映射

Machine profile 已完整声明 `B0..B14`。

R3 32 场景中：

- `R3-14` vision-only actionability → Phase 2 DEFERRED；
- `R3-29` native browser chrome/OS → Phase 3 DEFERRED；
- 其余 **30 个 Phase 1 场景**全部进入 `r3_phase1_fixture_map`。

但 map 当前只写：

```text
deterministic_fixture_before_browser_qualification
```

这表示**必须实现的资格义务**，不是“30 fixtures 已经 PASS”。

## 8. 验证记录（pre-commit）

### B-SPEC direct

```text
21 / 21 PASS
Ruff: PASS
Pyright: 0 errors / 0 warnings / 0 informations
py_compile: PASS
```

### SMC/SMX adjacency

组合：

```text
test_smc_browser_phase1_spec_v01.py
test_smc_contract_v01_conformance.py
test_smx_perceive.py
test_schema_lazy.py

75 tests collected
75 / 75 PASS
```

### Data/static/security

```text
JSON parse (profile/schema): PASS
git diff --check: PASS
privacy pattern scan: PASS
whole-tree security: PASS (1625 files at the four-core-file candidate state)
```

### Full repository gate

```text
whole-tree security: PASS (1625 files)
scripts/ci_gate.sh: exit 0
full Ruff: PASS
env-pin: 536 test files / 0 undeclared dependents
src Pyright: 0 errors / 0 warnings / 0 informations
tier0: PASS
xdist full suite: PASS
```

## 9. 非声明项

B-SPEC 没有：

- 新增 Browser production module；
- 连接真实 Chrome/Playwright session；
- 实现 stable-ID tracker；
- 执行 click/fill/select/navigate/scroll；
- 实现 receipt store；
- 调用 8901 或其它模型；
- 重启 8901/8903/Feishu；
- 证明 30 个 R3 implementation fixtures；
- 证明 Browser implementation conformance。

## 10. 下一阶段资格

若本阶段最终 full repo gate 与 committed-state 复核通过，推荐下一阶段是：

> **B-PERCEPTION：只读 DOM + AX perception adapter，先实现 scope/snapshot/object/grounding/hydrate，不实现 mutation。**

开始 B-PERCEPTION 前仍需新的明确用户裁决；B-SPEC 本身不授权自动进入下一 major phase。
