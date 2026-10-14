---
method_id: schema-precondition-check-before-instructed-state-transition-fa2c9a20cfbd
name: schema-precondition-check-before-instructed-state-transition
description: 执行他人指示的登记/核销/完成类状态迁移调用前，先一步读目标工具 Schema，提取状态前置条件与拒绝语义，再用记录类型+ID 的字面 token 一次查目标当前状态：两者一夹即得『指示可行 / 结构性不可行』，把跨记录类的多轮验证瀑布压成两步。不可行时凭权威拒绝回执上报缺口与积压规模，不绕人工护栏。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:43966c4f-fe71-4779-a054-72a945697fa7:602:8c7bd01f2c062adb3558
evidence_refs: learning:learn:bdcadb6224cc
created_at: 2026-10-13T23:02:29.925389+08:00
updated_at: 2026-10-13T23:02:29.925389+08:00
---
## Trigger
被要求执行某个带状态前置条件的登记/完成/核销类工具调用（如 executing→executed 的 completion 登记），且该调用是否可受理取决于目标记录当前状态；或需先裁决『按指示执行』是否本来就被工具契约排除

## Discriminator
工具 Schema 本身（一次 lookup 即得）明确写出状态前置条件（如『仅 executing 状态需登记完成』『不确定是否完成时不要登记』）与拒绝分支；记录库检索按字面 token 命中，record_type+ID 组合（如 evolution_exec + EVO-编号）一步返回当前状态——这两个事实在动手前即可取得，无需先翻历史记录正文

## Short path
- 读目标工具 Schema，提取状态前置条件与拒绝分支（未知量：调用在什么条件下被受理）
- 用 record_type+ID 字面 token 查目标记录当前状态，不用长自然语言短语（未知量：是否满足前置条件）
- 状态不满足前置条件 → 判定指示按设计不可行：至多做一次调用取权威拒绝回执，量化同类积压规模后上报缺口；不借 CLI/旁路绕过防乱登记护栏
- 其余子任务按各自事实推进：如按快照命中路径的相对路径不变量定位工作区同文件，读当前源码后重新下根因，不复用过期诊断

## Stop conditions
- 前置条件已知且目标当前状态已知，且已取得权威受理/拒绝回执或已明确报告不可行及缺口规模
- 不再对同一记录状态做换措辞的重复确认搜索

## Verification
- 实际回执分支与 Schema 预测一致（拒绝原因=状态不符，而非猜错语义）
- 积压/规模数字来自一次范围明确的枚举查询，而非逐页翻记录拼出
- 最终根因引用的行号/大小来自当前工作区文件，可对 HEAD 复核

## Counterexamples
- 幂等、只读或 Schema 无状态前置条件的工具：预检无收益，直接调用读回执更短
- 记录检索只是过期快照、真实状态并发变化时：一次直接调用本身就是权威校验，预检反而多余
- 指示自身已编码状态且调用廉价安全（『它已是 executing，请登记完成』）：直接调用可最短，不必先查
