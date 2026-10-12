# SMC Browser Typed Wait v0.6-A1 — Read-Only FCR Result — 2026-09-13

## 裁决

**A1 pre-registered gate: FAIL。A2 不启动。**

当前正式状态：

- v0.6-A0 typed Predicate compiler / canonical polling equivalence：**PASS**；
- v0.6-A1 real-model First-Call-Ready / live-capability qualification：**FAIL / NOT_QUALIFIED**；
- v0.6-A2 三任务 ×2 confirmatory：**NOT_RUN_BY_GATE**；
- v0.6-B navigation redesign：**NOT_STARTED**；
- cloud canary：**NOT_RUN**。

本轮失败不是 legacy `full_action`、scope/version blocker、mutation side effect、fallback 或 infra 导致。两行均在 exact read-only surface、同一 Ornith、fresh session/data/profile 下完成，并且模型都先 snapshot、都选中了预期 typed wait、首个 wait 都给出了完整六字段。失败暴露的是两个更窄的 capability/FCR 问题。

## 冻结身份

- v0.6 interface design：`ba6d93cd`
- A0 implementation：`07fe17f0`
- A0 deterministic equivalence：`080e38f9`
- A1 frozen protocol：`a978bf3a`
- A1 gate diagnostics enforcement / measured HEAD：`625a5fe9`
- A1 frozen plan SHA256：`9650bdb09b54fdaa7f55f3ec845979379ea7b973a0d4610721830a7af85b03b1`
- A1 provider surface SHA256：`15fd428653b325ef7d56f49bf8e8254d6d4e944787422f93873f22bee84ccecf`

运行固定：Ornith / 8901 单实例、Thinking ON、temperature 0、184K input / 16K output、max_iterations=8、worker timeout=180s、fresh session/data/Chrome profile、严格串行、无 fallback。Chrome 由 harness 机械预打开 loopback fixture；模型 surface 仅 `browser_perceive + browser_wait_scope + browser_wait_object + get_tool_schema`，无任何 Browser mutation tool。

## A0 资格状态

A1 失败不推翻 A0。A0 已证明：

- `browser_perceive` 模型面已缩为 `snapshot | hydrate | diff`；
- `browser_wait_scope` / `browser_wait_object` 机械编译固定 Predicate identity/schema 字段；
- exact object ref 使用 session-fenced hydrate；
- typed path 与 canonical `BrowserPredicateWaiter` 在 satisfied、indeterminate、coverage incomplete、observer-error recovery、sample_count 等机械语义上直接等价；
- scope/version/single-dispatch/ActionReceipt mutation 边界没有被修改；
- committed-state full CI PASS。

因此本轮应裁决为：**compiler mechanics qualified；provider/live FCR contract 尚未 qualified。**

## Frozen A1 gate

| 条件 | 结果 |
|---|---:|
| 完整 rows | 2/2 |
| infra valid | PASS |
| surface exact | PASS |
| no fallback | PASS |
| SecurityAgent | 0 |
| expected typed wait is first typed wait | 2/2 PASS |
| snapshot before first typed wait | 2/2 PASS |
| first typed wait exactly 6 required fields | 2/2 PASS |
| first wait `predicate_result=satisfied` | **0/2 FAIL** |
| typed wait tool failures | **6 FAIL**（均在 object row） |
| legacy `browser_perceive(wait)` misuse | 0 |
| `snapshot(predicate=...)` misuse | 0 |
| missing-predicate failures | 0 |
| scope-target-mismatch failures | 0 |
| mutation calls | 0 |

最重要的正证据是：v0.5 中反复出现的 “missing predicate / target=scope_ref / snapshot(predicate)” 这一整类模型合同错误，在 A1 中为 **0**。typed split 确实让模型第一次就知道“用哪个 wait 工具、给哪些顶层字段”。

## Row 1 — `scope_ready`

结果：**TASK_FAIL**，但 First-Call 结构正确。

- 第一调用：`browser_perceive(snapshot)` success；
- 第一 typed wait：`browser_wait_scope`，六字段完整；
- property=`document_ready_state`，operator=`eq`，value=`complete`；
- typed tool failure=0；legacy wait/snapshot(predicate)/missing-predicate/scope-target mismatch=0；
- first wait：`indeterminate`，sample_count=117，observer_error_count=0；
- 模型读取 `get_tool_schema` 后又原样调用一次 scope wait，仍为 indeterminate；
- 全程无 mutation/fallback/SecurityAgent。

**Exact root cause：`property_unobserved`。** Live CDP capture 没有提供 `document_ready_state`，所以 canonical evaluator 在完整 coverage 下仍只能返回 observed_value=null / indeterminate。

这不是 Predicate compiler 对条件做错了解释：它正确机械编译为 `schema=smc.predicate.v0.1 / domain=browser / target=scope_ref`。问题是 provider surface 宣称 `document_ready_state` 可等待，而当前 live sensor 没有供给该事实。它属于 **capability advertisement ↔ sensor fact mismatch**。

## Row 2 — `object_enabled`

结果：**TASK_FAIL**。同样先正确 snapshot 并选到 exact `Ready control` object ref。

- 第一 typed wait：`browser_wait_object`，六字段完整；
- property=`enabled`、operator=`eq`、exact object_ref 正确；
- legacy wait/snapshot(predicate)/missing-predicate/scope-target mismatch=0；
- mutation/fallback/SecurityAgent=0；
- 但 typed wait 共 6 次在 polling 前 fail-closed。

**Exact root cause：property-dependent `value` type 没有在 provider surface 上足够明确。** 模型前 5 次提交字符串 `"true"`，最后一次提交字符串 `"false"`；runtime 正确拒绝：`predicate value type mismatch for enabled: expected boolean`。没有开始 polling，也没有把字符串静默 coercion 成 boolean。

这里的 runtime 行为是正确的；问题在接口：当前顶层 `value` 为通用 JSON value，而 `enabled` 的布尔类型关系只存在于运行时 Predicate spec。真实 Ornith 证明这个关系是 **load-bearing First-Call fact**。

## 这轮真正证明了什么

### 已解决 / 有强正证据

1. **模型不再手写完整 Predicate identity。** schema/domain/target 机械关系已经从模型负担中移除。
2. **wait target kind 被工具名分开后有效。** 两行第一次都选择正确 scope/object wait。
3. **首调顶层结构稳定。** 两行 first wait 都精确六字段；missing predicate、scope-target mismatch、snapshot(predicate) 均为 0。
4. **fail-closed 边界正常。** 错 value type 没有 coercion；sensor 未观测事实没有被伪造成 false/true。

### 尚未解决

1. **Surface 不应宣传 live backend 实际不可观测的 property。** `document_ready_state` 在 schema/fixture-level deterministic tests 可成立，但当前真实 CDP sensor 未提供它。
2. **property → value type 仍由模型隐式推断。** 对 boolean property，Ornith 把自然语言 true 生成为 JSON string，说明通用 `value:{}` 对 FCR 不够明确。

## 架构裁决

不要回退 typed wait，也不要恢复模型手填 canonical Predicate。A1 的失败反而说明 typed compiler 已把问题进一步压缩到了两个接口真实性问题：

- **capability exposure 必须服从真实 sensor 能力**；
- **模型拥有 semantic choice，但机械 value type 不应靠猜。**

下一轮如果获批，应先只读设计如何让 provider surface 表达这些 load-bearing facts，同时保持 provider-agnostic 和 LLM-First。候选方向应优先比较：

- 让 CDP sensor真实提供 `document_ready_state`，而不是为了过测试删语义能力；
- 对 Predicate property 按机械 value type 分层/拆工具或使用更浅的 typed semantic fields，而不是 runtime 自动字符串 coercion；
- 保持 model 选择 object/scope、property、operator、expected semantic value；program 只承担 schema/identity/type/mechanical validation。

**不采用**：字符串自动转 boolean、自动替换 property、自动选择另一个 scope/object、retry/rebind/latest、扩大 universal prompt、重跑 A1 失败行、事后改 gate。

## Evidence hashes

- `results.jsonl`: `79f482a4427de174ea925b9f69d6ddd8657a8f6d36e34b47ad36a675a18b6f4b`
- `smoke-gate.json`: `ff4c8b45f42c6542c63c21aa73221036f95624385865d1654cbdc5511e4ca4cc`
- `execution-manifest.json`: `b728825a8adb862042eeab711e95eb12ef0f85a9f238e7769915a400e1c3340b`
- `plan.json`: `b102a2b430815c8babb62ced6dab098a0d8ed4589ffc36bb6d30a6bea5de4f7e`

Raw measured evidence 保持本地 untracked，不进入 commit；报告不包含运行时实例标识、浏览器实例路径、本机绝对路径或模型隐藏推理内容。
