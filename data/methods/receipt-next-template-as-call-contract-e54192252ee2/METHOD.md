---
method_id: receipt-next-template-as-call-contract-e54192252ee2
name: receipt-next-template-as-call-contract
description: 对受管控制面工具（如 service_control）发起写动作时，若触发该动作的只读回执已内嵌显式调用模板（next 字段给出 action/target/expected_generation 等命名参数与具体值），就把模板当权威调用契约逐字实例化，仅补模型侧决策字段（如重启哪个 target），不凭记忆拼参数。无模板或字段类型不明时先 get_tool_schema 一次再发完整调用；遇参数契约失败按失败回执一次性修正全部字段，不做局部试探。模板只给语法不给决策：动作范围、授权与 preflight 仍须单独裁决；模板代次过期时以冲突回执 current 重试。
aliases: 重启命令缺target参数, 回执next字段就是调用模板, 控制面调用照抄status回执参数, service_control参数契约失败先读schema, 别凭记忆拼restart参数
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:1876:0b9bc2a87ac6a31c8d97
evidence_refs: learning:learn:357e5a9d1ec6
created_at: 2026-10-28T09:08:48.877846+08:00
updated_at: 2026-10-28T09:08:48.877846+08:00
---
## Trigger
读只读控制面回执（status/convergence/audit 类）后，要向同一控制面发起参数化写动作（restart/update/publish 类），且回执中已出现显式调用模板（工具名+命名参数+本轮具体值）

## Discriminator
触发动作的那条回执是否已逐字给出完整调用形态：如 next 字段写明 action=restart, target=..., expected_generation=332，且回执自身的 current state（desired_generation=332、git_head）与模板值一致——一致时该模板即可执行契约，无需凭记忆拼参数或预先读 schema

## Short path
- 读 status/convergence 回执，记录 desired_generation 与 lagging 目标，作为本轮唯一基准事实
- 扫描回执 next 字段：有显式模板则参数照抄，仅代入模型侧决策字段（哪个 target），一次性发出含全部命名必填字段的调用
- 无模板或字段类型/enum 不明时，先 get_tool_schema(tool) 一次，再发完整调用
- 若仍遇参数契约失败回执，按该回执一次性修正全部字段重试，不做逐字段局部试探
- 拿到受理回执（action_id）即转入终态核对路径（status/event_stream），本轮不把受理当完成

## Stop conditions
- 调用被受理且 target/generation 与触发回执的 desired/lagging 一致
- 模板代次与回执自身 desired 不一致（他方已推进）：以冲突回执 current 重试一次，仍不一致则停手先核状态
- 模板不含本轮具体值、仅为通用示例文案：不构成契约，转 schema 路线

## Verification
- 受理回执的参数逐项等于『触发回执模板 + 本轮决策字段』
- 参数契约失败出现 0 次（模板路线）或不超过 1 次（schema 路线）
- 终态只通过 status(action_id)/event_stream 核对，受理不等于完成

## Counterexamples
- next 模板建议『逐个 restart 所有 lagging 服务』但用户只授权部分目标：模板给语法不给决策范围，不得因模板存在而扩大动作
- 非幂等/破坏性动作（publish、撤销、对外发文）不因有模板而跳过 preflight、独立审查或授权闸
- 模板值已过期（desired 被他方推进）时逐字套用会触发 CAS 冲突：应读冲突回执 current 重试，而非反复套旧模板
- 工具 schema 刚发生变更、旧回执模板语法失效时，先 get_tool_schema 校准再调用
