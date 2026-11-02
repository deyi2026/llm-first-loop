---
method_id: schema-vs-shared-gate-override-divergence-close-at-forwarding-site-d13043724604
name: schema-vs-shared-gate-override-divergence-close-at-forwarding-site
description: 共享权限/准入闸门函数若接受可选调用方 args，并按特定键名（如 cross_session+reason+evidence_refs）开启放行分支，则任何委托它、但 schema 与拒绝文案都未声明这些参数的工具，都会静默继承一条旁路：文案说不支持、实现却放行，同一目标两套规则。方法：diff『override 分支认的键名集』与『该工具 schema 参数集』，差集非空即在转发边界关闭旁路；行为回归用精确 bypass 参数组合断言确定性拒绝+后端状态不变；契约回归断言 schema 仍排除该参数；并把『override 是通用出路』的共享提示文案改为分域。
aliases: 工具没声明的参数却过了权限闸, 拒绝文案说不支持实际却放行, 共享闸门 args 后门排查, 白名单外参数绕过准入, 两套判定规则统一到转发点修, schema 不含的 override 参数却生效
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:3203:ed6f4b93f80d67ef9224
evidence_refs: learning:learn:7c18de9888eb
created_at: 2026-11-01T18:31:52.520427+08:00
updated_at: 2026-11-01T18:31:52.520427+08:00
---
## Trigger
审查或修复某工具的权限/准入判定缺陷（或评审 finding 指出同一目标存在两套规则、拒绝文案与放行行为互相矛盾）时，该工具的公开 schema 与拒绝文案声明某能力不支持、参数表不含 override 参数，但判定委托给一个接受可选调用方 args、且按这些参数名开启放行分支的共享闸门函数

## Discriminator
三处即可同时看到的集合差：①共享判定函数 override/授权分支实际认的 args 键名（读该分支定义）；②该工具 TOOL_DEF schema 的参数表（不含这些键）；③存在把调用方 args 原样转发进共享函数的 callsite。差集非空且这些键只出现在其他域工具的 schema 中，即判『未声明旁路』

## Short path
- 读该工具 TOOL_DEF 参数表与拒绝文案，记下声明的能力边界（如 supports_cross_session=False、无 cross_session/reason/evidence_refs）
- 沿委托边只读共享闸门函数的 override/授权分支，收集它实际认的 args 键名，不做全仓宽搜
- 做键名集合 diff：差集非空即判定『同一目标两套规则』，grep 定位转发 args 的 callsite
- 在转发边界修：非声明工具不再把调用方 args 传给共享 override 分支（或改显式 per-tool 能力位），不动合法声明该能力的工具
- 行为回归：手工构造精确 bypass 参数组合，断言确定性拒绝+命名 reason_code+后端账本字节/任务状态不变
- 契约回归：断言该工具 schema 仍不含 override 参数；同步把『通用 cross_session 出路』的共享提示文案改为分域说明

## Stop conditions
- override 键 ⊆ 该工具 schema 参数且文案已声明 → 属设计能力，不得当缺陷修
- 共享函数的 override 分支只由服务端身份/上下文触发，调用方 args 到达不了该分支 → 无旁路可关，停止此路径
- bypass 回归（拒绝+状态不变）与 schema 排除断言均通过，且该域既有 cross_session 用例未回归 → 关闭

## Verification
- 对修复后的工具手工传 override 参数组合：期望命名 reason_code 的拒绝、存储字节不变、任务状态不变
- grep 转发点确认非声明工具的 args 不再进入共享 override 分支，而合法声明该能力的工具调用路径未受影响
- 跑该域单测+架构/guard 测试：schema 断言与既有跨会话用例同时绿；文档/文案审查闸不再报该矛盾

## Counterexamples
- checkpoint_goal/update_goal 这类在 schema 与文案中显式声明 cross_session 的工具：键名 diff 为空，不能套此法『修复』或移除其 args 通道
- 共享闸门的 override 只读服务端 session/identity，用户参数不可达该分支 → schema diff 与旁路无关
- 工具 schema 本就声明透传/override 参数且文档化为逃生门 → 声明契约即真值，不存在未声明旁路
- 评审 finding 只是文案措辞问题而行为面已一致（无转发点） → 应走文案修订，不需行为回归
