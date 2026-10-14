---
method_id: definitive-path-failure-resolve-env-anchor-before-discovery-5d232889e078
name: definitive-path-failure-resolve-env-anchor-before-discovery
description: 绝对路径收到权威『目录不存在』回执（definitive，非超时/权限 transient）时，被证伪的是环境锚点假设而非检索策略：第一未知量是『真实工作区根在哪』，一条 pwd / git rev-parse 即可解决。不要重复同一失败路径，也不要在锚点未定时转入全库内容枚举或换措辞的记录检索。锚点确立后再做有界领域定位（权威账本/日志文件）与 git 工作区 delta 核对，把『我改过什么/没改什么』的范围断言建立在 VCS 真值上。本集两次同路径失败后先 search_files(*) 加多变体检索，到第 5 个动作才 pwd 取得真根。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:43966c4f-fe71-4779-a054-72a945697fa7:886:049e6ae6c1bd7daf842e
evidence_refs: learning:learn:199ba5f094cb
created_at: 2026-10-13T23:20:34.347388+08:00
updated_at: 2026-10-13T23:20:34.347388+08:00
---
## Trigger
假定的绝对路径/主机根收到明确『不存在』失败回执，cwd 或 repo 根尚未在本会话验证，而任务仍需继续定位文件、账本或记录时

## Discriminator
回执性质：明确 directory-not-found / 404 类 definitive 失败 ⇒ 路径锚点假设已被证伪，『真实根』成为第一未知量；若只是 timeout / 权限 / transient 错误，锚点未必错，不适用

## Short path
- 收到 definitive 路径失败回执后，不重发同一路径，先 pwd / git rev-parse --show-toplevel（或 ls 当前层）确立真实工作区根
- 在真实根下做有界目标域定位（如 ls data/audit、find -maxdepth 2 限定领域目录），找到权威账本/记录文件，替代全库内容搜索
- 直接查询权威记录（jsonl 账本、review log）拿目标条目的 status/时间戳/理由与计数
- 对『我只改过 X、没动 Y』类范围断言，用 git status + git diff 读工作区真值，借 diff 内嵌 provenance id（如提案编号注释）把每处修改归因到具体提案/会话，并单独列出 executed-未-verified、未提交的尾巴
- 关键事实经权威来源核验后即写入沉淀并停止，不再追加确认性查询

## Stop conditions
- 真实根已确立且权威账本已给出目标条目的最终状态（含时间戳与理由）
- 工作区 delta 已逐项归因，未验证/未提交的遗留项已显式列为独立事项
- 锚点解析本身不可用（连 pwd/根解析都失败）→ 转入环境诊断分支，而非继续内容层搜索

## Verification
- 后续所有文件访问均基于已确立的真实根，且没有第二次同因路径失败
- 最终断言中的状态字段（status/reviewed_at/verified_at 等）与权威账本原文逐字一致
- 范围更正类结论（如『某文件改动来自更早提案而非本轮』）同时有 git diff 与该提案记录双重支撑

## Counterexamples
- 回执是 transient（超时、权限、5xx）：路径可能存在，锚点未必错，应重试或诊断该路径而非换根
- 任务目标本身就是全库枚举/迁移盘点：broad discovery 是任务本身而非扩散
- 同会话早前已有成功读取证明 cwd 正确：不存在锚点未知量，直接沿既有路径继续
- 失败路径属于远端/沙箱主机：本地 pwd 与其无关，需要解析的是远端会话的根，而不是本地工作区
