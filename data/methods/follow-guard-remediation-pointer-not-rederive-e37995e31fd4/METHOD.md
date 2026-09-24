---
method_id: follow-guard-remediation-pointer-not-rederive-e37995e31fd4
name: follow-guard-remediation-pointer-not-rederive
description: 当工具拒绝/守护回执已点名替代命令并给出精确用法（如 CLI 子命令+参数格式）时，把它当作直接下一跳：只需一次定向查阅该命令 handler 的定义以确认剩余前置条件（状态机合法性），再按用法行逐字调用（含入口形式，控制台脚本名优先，失败后才换 -m 模块路径）；不要为确认已给出的信息重读整个分发/状态机子系统，也不要在合法性问题已解答后继续同路径源码枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:1710:96d6e231bee865de81cd
evidence_refs: learning:learn:1e9a6562b0a6
created_at: 2026-09-24T02:51:38.867966+00:00
updated_at: 2026-09-24T02:51:38.867966+00:00
---
## Trigger
工具拒绝/守护回执中包含显式补救指针：具名命令 + 精确用法字符串；剩余未知量仅是前置条件合法性或入口形式

## Discriminator
拒绝回执文本本身已含命令名与参数格式（`evolve-complete <id> "<结果说明>"`），且首次定向 grep 的输出已展示该子命令的分发行与 usage 行（cli.py:508-510，含入口点形式）。这些当时已可见的事实把『如何完成登记』缩小为『确认一个 handler 前置条件』。

## Short path
- 读拒绝回执，逐字提取具名命令与用法；唯一剩余未知：当前状态是否满足 handler 前置条件（accepted 能否登记 executed）
- 一次定向查阅该命令 handler 定义（grep 函数名 + 读其 docstring/body，如『涉边界 accepted/executing → executed』），确认前置条件覆盖当前状态
- 按用法行的入口形式逐字调用（usage 中给出的控制台脚本名优先；仅当失败才改用 -m 模块路径重试一次）
- 回执回显预期终态迁移（→ executed）即停止，不再读取同路径其他 handler 或状态机实现

## Stop conditions
- handler 定义确认前置条件覆盖当前状态，且调用回执确认目标状态迁移与 executor 归属
- 守护回执的建议与 handler 实现冲突时，以实现为准停止追随指针，如实上报而非强行调用
- 用户所需事实（登记完成）已由权威回执验证后，停止一切源码再确认

## Verification
- 命令输出回显预期的状态转换与 executor 标注
- 调用参数与回执/usage 行给出的格式逐字一致（含入口点 token）
- 前置条件确认后不再出现对同一子系统的额外 grep/sed 枚举

## Counterexamples
- 守护回执是泛化提示（如仅『权限不足』），未具名替代命令与用法 → 无可沿指针，进行更宽的调查是合理的
- 守护回执声称的前置条件与 handler 实现不符（实现仅接受 executing 而非 accepted）→ 不得按回执强行调用，须遵从实现的状态机并如实报告
- 任务目标本身是修改或评审该 handler 实现（而非调用它）→ 读源码是任务主体而非开销，此方法不适用
- usage 行为陈旧文档，与当前运行时 CLI 不一致 → 需先以 help/干跑确认真实入口，不能盲信任 何 usage 字符串
