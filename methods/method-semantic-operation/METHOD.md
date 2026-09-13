---
name: method-semantic-operation
method_id: method-semantic-operation
description: 使用 SMC/语义操作工具处理“观察世界、定位语义对象、带版本前置执行动作、读取机械回执、重新观察并验证任务状态”时使用。该方法不替模型选择目标、不自动重试/rebind，也不把 ActionReceipt 当作任务完成；当前首个资格化 domain profile 是 Browser Phase 1。
status: active
---
# Semantic Operation Method

本方法教的是**如何消费语义操作协议中的机械事实**，不是替你决定任务策略。

核心循环：

`Observe -> Ground -> Scope -> Act -> Receipt -> Re-observe/Verify`

程序负责提供当前 snapshot、SemanticObject、scope/version、grounding、ActionReceipt 与硬边界；**模型选择**要操作哪个对象、为什么操作、何时已经满足用户任务。

## 1. Observe：先取得当前世界事实

先读取当前 observation，再基于当前 observation 行动。不要把旧消息里的对象名、旧 snapshot id、旧 grounding 当成仍然有效。

Browser Phase 1 中：

- `browser_perceive(action=snapshot)` 取得当前 `snapshot.snapshot_id`、`scope_facts` 和 projected `objects`；
- projection 不完整时，用返回的 exact grounding ref `hydrate`，不要用名称猜缺失对象；
- `diff` / `wait` 是只读事实工具，不会替你执行 mutation。

## 2. Ground：从 observation 选择语义实体

先根据用户目标和当前世界事实选择语义对象，再使用它已经给出的稳定语义标识。不要构造 selector、XPath、坐标、CDP node id 或其它 backend locator。

Browser object mutation 的最小事实映射：

- `object.id -> target_id`
- `object.scope_ref -> scope_ref`
- `snapshot.snapshot_id -> expected_version`

对象是否是用户真正想操作的对象，由模型根据当前任务和 observation 判断；程序不做 task relevance 排序。

## 3. Scope：把动作绑定到正确的版本域

版本前置是 TOCTOU 保护，不是任务语义。

Browser Phase 1 当前 profile：

- `click/fill/select/scroll`：`version_scope=object`
- `navigate`：`version_scope=resource`
- mutation 不使用 `version_scope=snapshot`

对象动作使用该对象所在 observation 的 `snapshot.snapshot_id -> expected_version`。`navigate` 使用当前 **page scope** 作为语义根：page `scope_ref` 同时作为 `target_id` 与 `scope_ref`，并使用当前 `snapshot.snapshot_id -> expected_version`。

不要把 document/object scope 冒充 page resource scope，也不要自己发明 expected_version。

## 4. Act：一次提交一个明确 SemanticAction

先确定当前要做的一个动作，再提交一次。Browser Phase 1 的固定机械事实是：

- `schema=smc.semantic_action.v0.1`
- `domain=browser`
- `operation_class=mutate`
- `idempotency_class=unknown`
- `atomicity_class=single_dispatch`
- `version_precondition=required`

verb-specific args：

- `click`: `{}`
- `fill`: `{"text": <string>, "mode": "replace"|"append"}`
- `select`: `{"value": <string>}`
- `navigate`: `{"url": <http/https URL>}`
- `scroll`: `{"delta_pages": <number>}`，Phase 1 仅 semantic-object scroll

每个显式动作使用新的 `action_id`。不要因为没有看到期望结果就复用 action_id 或自动 replay。

## 5. Receipt：把 ActionReceipt 当机械事实，不当任务结论

`ActionReceipt status=ok` 只说明该 action 已按机械合同 dispatch/观察完成，**不等于任务完成**，也不等于页面达到了用户想要的语义结果。

- `status=ok`：读取 `after_version`、`observed_effects`、`boundary_events`、`completeness`；若还需继续任务，再决定是否 re-observe。
- `status=rejected`：动作没有获得合法 dispatch 条件。先解释 rejection 暴露的缺失事实，不要把 rejection 当成“换个目标再试”的指令。
- `status=failed`：dispatch/transport 的机械结果失败或不确定；不要假定没有副作用，也不要静默 replay。

## 6. 常见 rejection 的最小解释

这些不是固定 recovery workflow；它们只说明下一步判断前缺什么机械事实。

### `expected_version_unavailable`

你提供的 expected version 不能支持当前 precondition。重新取得当前 observation / exact grounding，确认所选对象或资源来自哪个 snapshot；不要猜 version。

### `resource_scope_mismatch`

你给出的 resource scope 与 expected version 中记录的资源不是同一个。重新读取当前 page/scope facts，并让 page `scope_ref`、target 和 expected version 来自同一 observation。不要仅因这个 rejection 再 navigate 一次。

### `args_contract_mismatch`

verb 的 args key 不符合 closed contract。读取当前 `browser_action` schema 或本 Method 的 verb args，修正参数结构；不要通过换目标绕过 schema 错误。

### stale / identity / target mismatch

世界已经变化、目标不在 expected observation、或 identity 无法稳定解析。不要名称匹配后自动 rebind；重新 Observe，再由模型选择当前对象。

### `document_generation_changed` / `scope_changed`

这是动作后观察到的机械边界变化。旧对象 grounding 可能已经属于上一代 document/scope；若任务还没结束，先 Re-observe，不要假定旧 target 继续有效。

## 7. Re-observe / Verify：用当前世界验证用户任务

如果 action 改变了页面、document generation、scope，或你需要确认副作用，重新取得当前事实。最终“任务是否完成”由模型根据用户要求和当前页面事实判断，而不是由 receipt status、工具 success 或程序 heuristic 裁决。

## 停止条件

可以结束当前任务，当模型已有足够当前事实支持用户要求已经满足，并且没有必要的未决 mechanical ambiguity。不要为了“确认一下”无界重复 snapshot；也不要在当前事实不足时因为某个 tool call `success` 就宣称完成。

## 反模式

- 从按钮文字猜 selector/XPath/坐标；
- 用旧 snapshot 的对象去操作已换代 document；
- `resource_scope_mismatch` 后重复 navigate，而不先修正 resource grounding；
- `expected_version_unavailable` 时自己编 version；
- rejected 后自动换目标、自动 retry、自动 rebind；
- `ActionReceipt status=ok` 就直接宣称整个任务完成；
- 把 Method 当强制步骤：若当前事实已经足够，可直接执行最短合法路径。

## 方法边界

本 Method 是 provider-agnostic 的操作方法，不依赖某个模型家族。它不改变 SMC runtime，不新增权限，不放宽 stale/version/identity 规则，不提供自动 recovery。未来其它 SMC domain 应复用 `Observe -> Ground -> Scope -> Act -> Receipt -> Re-observe/Verify` 核心循环，并由各自冻结的 domain profile 提供真实 verb/scope/args 机械合同。
