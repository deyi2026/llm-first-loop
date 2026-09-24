---
method_id: denial-signature-records-first-b749e7b81591
name: denial-signature-records-first
description: 当命令以环境级写拒绝签名失败（自有路径上 open-for-write 统一 EPERM，多个不同命令同点失败），且用户把故障归因于近期状态变化（如'重启禁用了你的工具'）时：先做两件窄检查——(1) 用被怪子系统自己的状态回执（admission/exception 记录）证实或证伪用户归因；(2) 用拒绝签名查询本环境沉淀的记录（experience store / docs / known-issues）。若命中 verified 记录，直接采用其规定的人机分工（如 staging+runbook：agent 出定向操作手册、用户在自己的终端通道执行）并停止；只有未命中才展开'谁施加了该边界'的全新 RCA，且止于解释与移交，绝不自行放宽安全边界。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:1435:3c72546885799617c47b
evidence_refs: learning:learn:6a05471dae6a
created_at: 2026-09-23T17:15:53.359258+00:00
updated_at: 2026-09-23T17:15:53.359258+00:00
---
## Trigger
工具/命令失败，且失败签名是按操作类或路径类一致的环境拒绝（如 EPERM 'Operation not permitted' 落在账户自有路径的写操作上，多个不同命令在同一写点失败）；同时用户提出一个把故障归因于近期事件（重启/变更/开关）的因果理论

## Discriminator
回执级事实：失败点是对锁文件的 open-for-write EPERM 而非命令特异错误（stop 与 restart 死在同一处 mutation lock 写），说明是写类/路径类环境边界而非'某工具被禁'；随后被怪子系统自己的回执显示 admission/exception 均为空——当场即可证伪用户归因，并把候选空间从'任何可能禁用工具的机制'缩为'已知环境写边界，查有没有既有记录'

## Short path
- 执行用户指定的动作一次，抓取精确失败签名（errno 落在哪个操作/路径上）——解决未知量：失败是命令特异还是类级写拒绝
- 用被怪子系统自己的状态回执（admission/exception/pending）做一次归因检验——解决未知量：用户的因果理论是否成立
- 以拒绝签名（errno + 操作类 + 路径类）为关键词查询环境沉淀记录（experience store / docs / known-issues）——解决未知量：该边界是否已知且有既定应对模式
- 若命中 verified 记录：按其规定的分工输出定向 runbook（命令与回执中的失败路径/命令一一对应），交用户在自己的通道执行，并给出修正后的因果解释，停止
- 若未命中：才展开全新 RCA（边界施加者、配置来源、历史变更），且止于解释与移交，不自行改动安全边界

## Stop conditions
- 已用被怪子系统的回裁判定用户归因不成立，且一条 verified 记录解释了拒绝签名并给出可执行的人机分工
- 交付的 runbook 命令与回执中的确切失败路径/命令一一对应，用户侧可一次执行完成原目标

## Verification
- 确认拒绝是类级而非单次抖动：至少 2 个不同命令在同一路径类的写操作上以同一签名失败
- 引用的记录为 verified/active 状态，而非过时假设或未验证推测
- runbook 中的命令指向回执里的确切路径与命令，而不是泛化建议
- 被怪子系统的回执确无任何禁用/异常条目，归因证伪成立

## Counterexamples
- EACCES 源于真实权限位（如误 chown 给 root）：应修所有权而非套 runbook，EPERM 沙箱类记录会误导
- 失败是暂态锁竞争（BlockingIOError、锁超时、挂起进程持锁）：应查进程与锁状态，而不是查边界记录
- 环境中不存在 experience/docs/known-issues 记录库：短路不可用，全新 RCA 就是正路
- 被怪子系统回执确有 admission barrier 或异常记录：用户归因成立，应调查该子系统本身而非环境写边界
