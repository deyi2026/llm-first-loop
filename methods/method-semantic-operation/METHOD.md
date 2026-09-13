---
name: method-semantic-operation
method_id: method-semantic-operation
description: 使用 SMC/语义操作工具处理“观察世界、选择语义对象、执行动作、读取机械回执、重新观察并验证任务状态”时使用。Browser 的机械编译已经内置在 browser_semantic_execute 工具中；该方法不替模型选择目标、不自动重试/rebind，也不把 ActionReceipt 当作任务完成。
status: active
---
# Semantic Operation Method

本方法教的是**怎样使用语义执行工具**，不是教模型手工拼底层 SemanticAction，也不是让程序替模型决定目标或任务完成。

核心循环：

`Observe -> Ground -> Execute -> Receipt -> Re-observe/Verify`

程序负责提供 observation、GroundingRef、机械编译、版本前置、ActionReceipt 与硬边界；**模型选择**要操作哪个对象、执行哪个 verb、传什么业务参数，以及什么时候用户任务已经满足。

## 1. Observe：先看当前世界

Browser 中先调用：

`browser_perceive(action=snapshot)`

它返回当前 `snapshot`、projected `objects`、每个对象的 exact `SemanticObject.grounding_ref`，以及当前页面的 model-facing snapshot result `resource_ref`。

不要从旧消息里的按钮名、旧 snapshot、旧 ref 直接行动。页面可能已经变化。

## 2. Ground：模型只选择 exact GroundingRef

根据用户目标和当前 observation，模型自己选择目标：

- `click/fill/select/scroll`：选择当前 `SemanticObject.grounding_ref`；
- `navigate`：使用当前 snapshot 返回的 `resource_ref`。

不要构造 selector、XPath、坐标、CDP node id，也不要按名称自己发明一个 ref。

对象是不是用户真正想操作的对象，仍由模型判断；目标选择权不属于工具，工具也不做 task relevance 排序或“最佳目标”选择。

## 3. Execute：调用 browser_semantic_execute

模型只提交：

- `verb`
- `target_ref`
- `args`

例如点击 Commit：

1. `browser_perceive(action=snapshot)`；
2. 在返回的 SemanticObject 中找到符合用户意图的 `Commit` 对象；
3. 取它已经返回的 `SemanticObject.grounding_ref`；
4. 调用 `browser_semantic_execute(verb=click, target_ref=<Commit grounding ref>, args={})`；
5. 读取 ActionReceipt；
6. 再 `browser_perceive(action=snapshot)`，根据当前页面事实判断任务是否真的完成。

这就是标准的一次“带着做一遍”。

verb-specific args：

- `click`: `{}`
- `fill`: `{"text": <string>, "mode": "replace"|"append"}`
- `select`: `{"value": <string>}`
- `navigate`: `{"url": <http/https URL>}`
- `scroll`: `{"delta_pages": <number>}`，Phase 1 仅 semantic-object scroll

## 4. 工具内部做什么：机械编译，不做语义决策

`browser_semantic_execute` 工具内部会从 exact ref 机械恢复并派生底层 SemanticAction 所需字段，包括：

- `target_id`
- `scope_ref`
- `expected_version`
- `version_scope`
- `action_id`
- `schema/domain/operation_class/idempotency_class/atomicity_class/version_precondition`

对象动作机械绑定 object scope；navigate 机械绑定 page resource scope。模型不再手工填写这些字段。

同一个 exact `target_ref + verb + args` 会得到同一个确定性 `action_id`。因此重复提交同一 exact request 会被现有 single-dispatch 防重机制拒绝，而不是再次执行物理动作。若世界变化后任务仍需下一动作，应重新 Observe，由模型重新选择当前 ref；工具不会自动 retry、replay、latest 或 rebind。

## 5. Receipt：ActionReceipt 是执行事实，不是任务结论

`ActionReceipt status=ok` 只说明该动作经过当前机械合同执行/观察，**不等于任务完成**，也不证明页面已经达到用户想要的语义结果。

- `status=ok`：读取 `after_version`、`observed_effects`、`boundary_events`、`completeness`，再决定是否需要重新观察；
- `status=rejected`：当前动作没有满足合法 dispatch 条件，不要把它理解成“自动换目标再试”；
- `status=failed`：执行结果失败或不确定，不要假定没有副作用，也不要静默 replay。

## 6. 常见 rejection / compile rejection 怎么理解

这些只说明缺了什么机械事实，不是固定 recovery 脚本。

### `target_ref_unavailable` / `target_ref_expired` / `target_ref_unauthorized`

当前 exact ref 不能被本 session 合法使用。重新 Observe 取得当前 observation；不要猜 ref，不要跨 session 复用。

### `target_ref_projection_mismatch`

verb 与 ref 类型不匹配，例如对象动作拿了 page resource ref，或 navigate 拿了 object ref。重新检查当前 observation 中已经返回的 ref 类型。

### `expected_version_unavailable`

底层版本前置无法支持当前 dispatch。重新 Observe；不要自己编 expected version。工具会从新的 exact ref 机械派生版本。

### `resource_scope_mismatch`

当前 page resource 与 version grounding 不一致。重新 Observe 并使用当前 snapshot 的 `resource_ref`；不要因为这个 rejection 自动再 navigate 一次。

### `args_contract_mismatch`

verb 的 `args` 不符合 closed contract。按 `browser_semantic_execute` 工具描述修正参数结构，不要换目标绕过参数错误。

### stale / identity / target mismatch

世界已变化、目标不再属于 expected observation，或 identity 无法稳定解析。不要按名称自动 rebind；重新 Observe，再由模型选择当前对象。

### `document_generation_changed` / `scope_changed`

这是动作后观察到的机械边界变化。旧对象 ref 可能属于上一代 document/scope；如果任务还没结束，先 Re-observe。

## 7. Re-observe / Verify：模型判断用户任务是否完成

动作之后若页面、document、scope 或目标状态可能变化，调用新的 snapshot。最终“任务是否完成”由模型根据用户要求和**当前页面事实**判断，而不是由 receipt status、ToolResult success 或程序 heuristic 裁决。

## 停止条件

当当前事实足以支持用户要求已经满足，并且没有必要的未决机械不确定性，可以结束。不要为了“确认一下”无限 snapshot；也不要因为一次 tool success 就直接宣布完成。

## 反模式

- 模型手工拼 `target_id/scope_ref/expected_version/version_scope/action_id`；
- 从按钮文字猜 selector/XPath/坐标；
- 用旧 ref 操作已经换代的 document；
- rejected 后自动换目标、自动 retry、自动 rebind；
- `resource_scope_mismatch` 后盲目重复 navigate；
- `ActionReceipt status=ok` 就宣布整个任务完成；
- 把 Method 当强制步骤；当前事实足够时应走最短合法路径。

## 方法边界

本 Method provider-agnostic，不依赖具体 provider 或 model family。Browser 的 SemanticAction 机械编译封装在工具内部，但 stale/version/identity/single-dispatch 边界仍由已有 runtime 执行器负责。该工具不新增权限；目标选择权和任务完成判断权都留给模型，也不存在自动 recovery。
