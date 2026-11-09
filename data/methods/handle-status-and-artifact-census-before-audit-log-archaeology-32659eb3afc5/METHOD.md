---
method_id: handle-status-and-artifact-census-before-audit-log-archaeology-32659eb3afc5
name: handle-status-and-artifact-census-before-audit-log-archaeology
description: 断点续跑且状态快照已点名在途句柄（如审查/子代理句柄）时，恢复面是该句柄的一次 status 回执 + 按句柄落盘的权威产物目录（一次 ls 即得句柄全集），而不是对 append-only 审计日志反复换过滤条件（时间段→句柄id→动作串→精确时间戳）重演中断前历史。本集对同一 jsonl 连续 8 次改参 grep，而终态判决（REVISE）与修复提交在前两步就已齐备；产物目录里没有文件的句柄=从未产出，一次 status 即确认死亡，无需考古。与『stale-handoff 核对终态观测量防重执行』互补：这张防的是日志考古式状态重建。
aliases: 续跑先查句柄状态别翻审计日志, 断点恢复看回执目录就知道有几个子代理, 恢复现场不要反复grep流水账, 快照点名了子代理就直接status, 日志考古前先ls产物目录
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8641d508-e8f7-4b4c-86d8-c698c6927b74:1173:157ec29d70bf46e8e346
evidence_refs: learning:learn:8396c3512698
created_at: 2026-11-10T00:53:49.161181+08:00
updated_at: 2026-11-10T00:53:49.161181+08:00
---
## Trigger
中断后续跑（极简『继续』/超时唤醒），task-state 快照命中并点名在途句柄，且系统存在 per-handle status 通道或按句柄落盘的权威产物目录；此刻想弄清『中断前到底发生了什么、还有谁在跑』

## Discriminator
快照点名的句柄 id 本身 + 该句柄 status 一次回执（终态+findings+报告路径）+ 分支/lane 当前 head 是否已含判决所要求的修复。这三项合起来已能决定下一步；产物目录文件名全集=句柄普查（无文件⇔从未产出，死句柄无需处理）

## Short path
- 对快照点名的句柄发一次 status → 拿终态判决与报告路径（未知量：在途任务结束没有、要求改什么）
- 读分支/lane 当前 head 一次 → 确认判决要求的修复是否中断前已提交（未知量：我还欠什么改动）
- ls 按句柄落盘的产物目录一次 → 句柄普查：有文件=已产出；快照之外的可疑 id 至多补一次 status 确认死亡（未知量：还有没有别的在途句柄）
- 直接执行快照剩余管道的下一步（如对修复后 head 续审/续跑），不回溯会话历史
- 仅当某个句柄既无产物又无 status 解释、且语义上必须解释时，才做一次限定在[快照时间,now]窗口内的日志查询

## Stop conditions
- 具名句柄已达终态、修复归属已确认、句柄普查无未解释的在途项，且下一步动作已由快照管道确定
- 对同一日志文件的 grep 第二次只换过滤条件仍未产生新事实

## Verification
- 重放检查：每个被采信的句柄状态都有 status 回执或产物文件背书，而不是仅由日志行推断
- 续跑动作基于当前实际 head/终态，而非快照时刻的旧状态

## Counterexamples
- 快照 miss、没有任何具名句柄——应走工作区 delta/git status 找在途工件，不适用本卡
- 产物目录不按句柄落盘且无 per-handle status 通道的系统——句柄普查只能靠有界日志查询
- 交付物本身就是取证（谁在何时启动了什么）——日志考古是任务本体而非开销
- 怀疑某句柄仍占并发额度/烧 deadline 且无产物可查——一次窗口化 trace 查询正当，但全会话扫描仍不正当
