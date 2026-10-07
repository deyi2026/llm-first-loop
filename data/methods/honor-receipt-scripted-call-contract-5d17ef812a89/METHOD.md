---
method_id: honor-receipt-scripted-call-contract-5d17ef812a89
name: honor-receipt-scripted-call-contract
description: 当同一会话内先前工具回执已给出下一跳的精确调用模板（如 next: service_control(action=restart, target=..., expected_generation=N)），或契约拒绝回执已点名缺失字段（missing=target）时，下一次调用必须逐字转录这些参数名与取值，而不是凭记忆重构调用形状。收到契约拒绝后禁止原样重发：按回执一次性补齐全部字段，enum/类型不明时读一次 get_tool_schema 即可。适用于发布/重启等控制面调用及任何带显式契约回执的工具。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:1906:2c520ec366a341c21583
evidence_refs: learning:learn:daf0e76c67ae
created_at: 2026-10-07T14:25:14.007495+08:00
updated_at: 2026-10-07T14:25:14.007495+08:00
---
## Trigger
即将发起 service_control 等控制面调用，且本会话先前回执已含显式 next 调用模板，或刚收到参数契约拒绝回执

## Discriminator
先于重试已存在的契约事实：publish 回执的 next 字段给出完整调用签名（含 target=...），契约拒绝回执点名 missing=target 并指示按回执一次性修正或先读 schema。该事实当时已把『参数怎么填』从猜测空间缩成一次转录。

## Short path
- 发起调用前先扫描最近相关回执是否含 next/示例调用模板；有则逐字转录参数名与取值
- 无模板且不熟悉契约时，首次调用前读一次目标工具 schema，再发调用
- 收到契约拒绝回执：不得以相同形状重发；按回执点名的缺失/非法字段一次性补齐（enum 可取自邻近 status 输出或一次 schema 读取）
- 以 accepted 回执（action_id）为界推进到下一目标，不在同一分支叠加重复尝试

## Stop conditions
- 拿到 success/accepted 回执即停止修正循环
- 同一调用形状在首次契约拒绝后至多重发一次，且必须已按回执变更字段
- 回执 next 模板与最新 status 冲突（如目标已有屏障或已收敛）时停止转录，先复核状态

## Verification
- 修正后首次重发即 accepted，不出现第二次相同 missing 字段的拒绝
- 每个目标服务恰好一次受理，action_id 可回查终态
- 全流程契约拒绝数 ≤1

## Counterexamples
- next 模板与更新后状态冲突（该 target 已有非终态动作或已收敛到期望代）：先 status 复核再决定，不盲转录
- 拒绝原因不是缺字段而是语义/权限/前置门禁：转录无法解决，应按回执指向的出口（release/adopt/override）处理
- 失败回执未点名缺失字段且无模板可依：只能退化为 schema-first 读一次，本方法不覆盖
- 错误源于环境假设（如 workdir 默认路径）且回执未提供路径线索：需先 pwd/发现真实环境，转录方法不适用
