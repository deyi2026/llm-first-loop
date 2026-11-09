---
method_id: contract-rejection-clear-all-dimensions-and-cas-scope-before-refanout-d474efd0f2a4
name: contract-rejection-clear-all-dimensions-and-cas-scope-before-refanout
description: 对控制面一批变更调用（字段名、CAS 期望代等多个契约维度未验证）被确定性拒绝时，不要只补丁回执点名的一个字段就重发整批：回执若给契约源（如 get_tool_schema）或明示『一次性修正全部字段』，先读契约源把全部维度一次清零；CAS 期望值取守卫比较的部署/desired-state 口径（拒绝回执 current=N 即权威值），而非目标服务行内 verify 代。本集 3 目标×2 轮=6 次拒绝可压缩为 1 次契约读取+1 批成功。
aliases: 参数被拒别一个字段一轮地试, 回执说一次性修正全部字段时先读schema, expected_generation填部署代还是服务代, CAS期望值用哪个generation口径, 批量restart契约错误一次改完, restart_target还是target字段
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c0fcfe68-fb12-4d65-894f-e765836fa751:76:afd676acc9ecb7ced5a9
evidence_refs: learning:learn:3005634d18f2
created_at: 2026-11-09T16:53:39.893253+08:00
updated_at: 2026-11-09T16:53:39.893253+08:00
---
## Trigger
需对控制面发起一批带契约参数的变更调用（如逐服务 restart），参数含≥2 个独立受契约约束的维度（必填字段名、CAS expected_generation），首批被确定性拒绝且回执点名一个缺失字段、同时提供契约源或明示『一次性修正全部字段』；或状态回执中同名量存在多口径（部署级 generation vs 服务行内 verify generation）

## Discriminator
回执是确定性参数/守卫拒绝（missing=target、generation expected≠current）而非瞬断；且当时已可见：(a) 回执自带契约源读取入口与『一次性修正全部』措辞，(b) 状态回执同屏两个 generation 口径（部署 402 vs 行内 400）而守卫名为 desired-state——CAS 期望值绑部署/desired-state 口径，行内 verify 代是诱饵

## Short path
- 发起变更批前：若字段名未在任何权威回执中逐字出现、或期望代存在多口径，先一次 get_tool_schema(service_control) 钉死字段名与 expected_generation 的比较口径
- 首批被拒后：不按点名字段单补丁立即重发整批；先读契约源，把字段名、枚举、CAS 口径全部一次清零
- CAS 期望值取部署/desired-state generation（拒绝回执 current=N 或状态回执 deployment.generation），不取目标服务行内 verify 代
- 维度全清后一次重发整批；受理≠完成，按 next_check 的 action_id 异步核终态
- 全部目标 status=succeeded 且 live.git_head==desired、convergence.lagging 清空后停止

## Stop conditions
- 契约源确认全部字段名/枚举/CAS 口径后，重发回执为 accepted（含 action_id+next_check）且后续不再出现契约类拒绝
- 拒绝属瞬时/环境类（timeout、5xx、rate-limit）：不进契约考古，按原参数退避重试
- 单维度调用且唯一违规已被回执点名：单补丁重发即最短路径，无需先读 schema

## Verification
- 重发整批零契约拒绝；若再拒，核对回执 current=N 与所用期望值口径一致
- 逐 action_id 核 status=succeeded 且 live.git_head==desired.git_head（convergence.lagging 不再含该服务）
- 沉淀契约经验时附可执行当前性锚点（如 grep 单测文件:行号确认契约断言仍存在）

## Counterexamples
- 瞬时失败（网络/限流/5xx）被误当契约违反：读契约源无益，应原样退避重试
- 单字段调用且唯一违规维度已被点名：单补丁重发更便宜，先读 schema 反而多一跳
- 状态回执只有单一 generation 口径（部署=行内）：CAS 口径歧义不存在，首批即应成功，本方法 CAS 子判据空转
- 纯只读查询调用无 CAS 守卫：只需字段名正确，本方法后半不适用
