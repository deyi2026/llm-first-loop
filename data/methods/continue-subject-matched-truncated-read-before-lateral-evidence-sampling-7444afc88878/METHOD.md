---
method_id: continue-subject-matched-truncated-read-before-lateral-evidence-sampling-7444afc88878
name: continue-subject-matched-truncated-read-before-lateral-evidence-sampling
description: 在 evidence 库中回答“先前某次观察的细节”时，若某条 hydration 的已读头部已确认该 artifact 正是目标主题的来源（如命令头正是那次 git status 扫描），而 envelope 同时显示 complete=false、next_start 非空，则该 ref 的未读余量是当前最窄的下一跳：立即按 next_start 续读同一 ref 直至 complete 或已获得答案，而不是横向 hydrate 其他 ref（尤其是命令头/label 与问题无关的，如 ls webui/dist、sleep 45 之类）。只有这条边读尽仍不含目标信息时，才扩大到横向采样其他证据。把分页 envelope 当作指令而不是元数据。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:18e51b8e-580f-47b5-a867-ad21b62684b1:987:3e9ff9e0ea97d772f1aa
evidence_refs: learning:learn:1b8580d1f995
created_at: 2026-10-08T20:25:32.010846+08:00
updated_at: 2026-10-08T20:25:32.010846+08:00
---
## Trigger
需要从 evidence 库找回某次先前观察的完整内容（如某命令输出、dirty 列表）；某条 evidence hydration 已显示其内容头/命令与问题主题匹配，但同一回执的 range 字段给出 complete=false 且 next_start 非空（读取被截断、余量未取）。

## Discriminator
两个当时已可见事实的组合：(1) 已读区间的正文头明确标识该 artifact 就是目标主题来源（例：'[命令] for d in …/llm-first-loop …/llm-first-loop-mirror … [输出 29 行]'，正是问题所指的发布前 git status 扫描）；(2) 同一 hydration envelope 写明 complete=false / next_start=200。两者同时成立即把“下一个该读什么”从所有候选 ref 缩到恰好一个：该 ref 的剩余区间。

## Short path
- 按 acquired_at / source label 把候选 evidence 与问题指涉的时间点对齐（“刚才发布前”→ 对应时刻的 execute_command 记录）
- 读目标 ref 的第一页（0..limit），仅用于确认主题匹配
- 若主题匹配且 complete=false：立即按 next_start 续读同一 ref，直到 complete 或已含所需列表/事实；此期间不 hydrate 其他 ref
- 从完整内容提取答案所需事实（完整 untracked 路径列表→按目录归类→由路径语义与时间戳归属写者）
- 若用户还问当前状态：对 live 资源补一次新鲜观察，核对快照与现场的差（30→31，untracked 不入 release）
- 停止

## Stop conditions
- 续读区间已包含回答问题所需的完整事实（如完整文件列表与归属依据）
- 同一 ref 已读到 complete=true 且仍不含目标信息——此时才允许横向采样其他 ref

## Verification
- 最终引用的 evidence ref 的命令头/主题与用户问题一致，且该 ref 已被读到 complete
- 关于“现状”的断言基于新鲜观察而非早前快照，并明确区分快照时间点与现场核对时间点

## Counterexamples
- 可见部分已完整回答问题（complete=true，或截断点之后只是尾部噪音）——不为“读完”而续读，直接进入分析
- 内容头与问题主题不匹配（如 ls webui/dist、sleep 45 的输出）——其截断与问题无关，续读它不是本方法的下一跳
- 检索协议没有分页 envelope（无 complete/next_start 字段），或 artifact 一次即读完——无剩余区间可续，本方法不适用
