---
method_id: truncated-noise-projection-pivot-to-narrow-authoritative-record-fe1e44d88c7b
name: truncated-noise-projection-pivot-to-narrow-authoritative-record
description: 当状态/控制类工具回执是全量投影，且在与目标未知量无关的长审计/诊断数组（如 generation_lag 历史）中途被截断、吃掉所需的每目标当前字段时，重复同参数查询或对 blob 分页大概率再撞同一形状。应立即改读该域按目标命名的权威窄记录（per-target manifest + desired-state 账本），一次取齐精确 pid/git_head/started_at 与目标 generation 的差值，再下发动作；对异步动作坚持『受理≠完成』，以窄记录复核终态。适用于任何『聚合工具投影噪音大、但域内存在更窄真值记录』的核实场景。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:1292:f321d194081f0577b167
evidence_refs: learning:learn:c6c4f577459b
created_at: 2026-10-18T10:12:07.324109+08:00
updated_at: 2026-10-18T10:12:07.324109+08:00
---
## Trigger
需要核实多个目标的当前运行状态；控制面工具回执为全量投影，被与所需事实无关的历史诊断/审计数组淹没并在数组中途截断，首次重试返回相同形状。

## Discriminator
回执截断点落在历史诊断数组条目流内部，而所需事实只是每目标少量当前字段（pid/git_head/started_at/是否需重启）；该域同时存在按目标命名的窄权威记录与 desired-state 账本，可直接一次读齐——截断发生在噪音数组内这一事实本身，就预示同查询重试与分页都会重复落在噪音里。

## Short path
- 识别回执形状：截断发生在无关诊断数组内部、所需为 per-target 当前字段 → 判定同参数重试/对 blob 分页大概率同形状，停止这条分支
- 立即定位该域按目标命名的权威窄记录：一次 grep 源码路径模板或直接列 runtime/data 目录，找到 per-target manifest 与 desired-state 账本
- 读各目标 manifest 取精确 pid/git_head/started_at，读 desired 账本取目标 generation，得到量化差值（落后多少提交/代）
- 基于差值下发动作（如 restart），按参数契约一次给全字段，保留 action_id；受理≠完成
- 登记异步终态核对：status(action_id) 查终态 + 同一 manifest 复核 pid/started_at 已更新、git_head 与 desired 对齐

## Stop conditions
- 已从窄权威记录取得所有目标的当前状态，并与 desired 状态精确对齐（含差值量化）
- 工具存在且验证有效的过滤/字段参数，可一次取回窄结果
- 发现磁盘窄记录为异步快照、滞后于控制面实时真值，则回退到工具投影并按需分页

## Verification
- 窄记录间交叉验证：各目标 manifest 的 git_head 与 desired-state 账本的 git_head/generation 对比；pid/started_at 时间合理性
- 动作受理后以终态回执 + 窄记录更新双重确认（pid 更换、started_at 刷新、git_head 对齐），不以受理当完成

## Counterexamples
- 工具支持有效的 target/fields 过滤参数时，收窄重试一次即可，无需下磁盘找记录
- 用户目标就是那段诊断数组本身（如查 lag 历史）时，分页/过滤读数组才是正解，窄 manifest 反而没有该信息
- 窄记录是异步落盘快照、控制面工具才是实时真值时，改读磁盘会取到过期事实
- 单目标查询且回执未被截断时，直接读结果即可，任何绕行都是浪费
