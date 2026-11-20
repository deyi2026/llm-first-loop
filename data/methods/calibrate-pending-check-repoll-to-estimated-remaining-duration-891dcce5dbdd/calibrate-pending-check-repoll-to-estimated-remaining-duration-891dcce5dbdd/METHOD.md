---
method_id: calibrate-pending-check-repoll-to-estimated-remaining-duration-891dcce5dbdd
name: calibrate-pending-check-repoll-to-estimated-remaining-duration
description: 长流程收口到唯一剩余未知量=某个外部异步检查（CI 门禁/构建）仍 pending、其余检查均已终态且该行身份稳定时，轮询节奏必须由『估计剩余时长』决定而不是固定短间隔：用先例（同一套件此前全量耗时）+该行 elapsed 推算下限，先把已核事实写入账本，再把后续查询窄化到该 pending 行，注册一次间隔≥估计时长的延时唤醒并先交付阶段报告。环境 repeat_guard（同一精确调用已第N次成功）是硬停信号：立即停止重查→账本→改排程。同一查询全程≤初查+终查两次，每次重查必须带来新终态信息。
aliases: CI 一直 pending 别反复刷, 门禁还在跑该等多久再查, 别用固定间隔盯异步检查, 到点醒来查一次而不是空转轮询, 外部任务卡在 running 怎么办
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:682e688e-107e-4abb-9ed7-0c7b1729f4d5:0:624a87d5c55a45718a1c
evidence_refs: learning:learn:5de819aa4d0d
created_at: 2026-11-17T08:19:45.482352+08:00
updated_at: 2026-11-17T08:19:45.482352+08:00
---
## Trigger
推送/PR/发布等长流程只剩一个未知量=某外部异步检查 pending，其余检查均已终态、该 pending 行身份稳定（名称/job URL 已知），且其完成由外部 runner 控制而非本端。

## Discriminator
决策时刻已可见且足以裁定：唯一 pending 行 elapsed≈0，而同类重检查的实测耗时与同一套件此前全量运行的先例量级均表明剩余时长为分钟级以上，任何短于该量级的重复查询期望信息增益≈0；若环境 repeat_guard 已报告同一精确调用重复多次并要求先记账本，则重复已越过机械阈值。

## Short path
- 对检查列表做一次全量读取并分类：已 pass / 唯一 pending（记名称+job URL）/ 按计划跳过
- 用先例耗时与 pending 行 elapsed 推算剩余时长下限
- 把已核事实+pending 身份+未决+下一步写入任务状态账本
- 后续核查窄化到该 pending 行（按名称过滤或直查该 job 状态），不全量重列
- 注册一次延时唤醒，间隔≥估计剩余时长；先交付阶段性报告再等待
- 唤醒后单次窄查：pass→交付完成终报；fail→抓取失败详情如实上报

## Stop conditions
- 权威来源确认 pending 项终态（pass/fail），未知量闭合
- pending 行 elapsed 已接近或超过先例估计总时长→未知量转为疑似挂死，改做健康/超时探查，不再定时等待
- 出现任务边界禁止的请求（合并/改 main/强推等）→停止并上报

## Verification
- 同一检查查询的重复次数≤2（初查+终查），且每次重查回执都含新终态信息
- 账本写入早于任何冗余轮询，且含已核事实、引用、未决、下一步
- 终报中的 SHA/PR/构建状态与权威回执逐字一致

## Counterexamples
- 多个检查会在轮询窗口内陆续翻转为终态（每轮全量重列都有新信息）→全量重查增益为正，窄化与长间隔规则不适用
- pending 原因是外部人工未行动且完成时刻不可估计（审批类）→应走 report-blocked 收口，不排定时唤醒
- 状态可能在短于估计值内翻转（快速失败型检查）→允许首次短延迟确认一次，之后才按估计时长校准节奏
- pending 行已超时或长期无进展迹象→下一动作是探活或人工上报，不是再等一轮
