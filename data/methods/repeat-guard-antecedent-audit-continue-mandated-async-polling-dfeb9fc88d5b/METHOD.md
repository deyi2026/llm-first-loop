---
method_id: repeat-guard-antecedent-audit-continue-mandated-async-polling-dfeb9fc88d5b
name: repeat-guard-antecedent-audit-continue-mandated-async-polling
description: 按任务书执行 wait→status 异步轮询（review_admission 等门禁/子代理）途中，反重复守卫报警并建议『事实已核则记账、勿重复探索』时，先审计守卫前件而不是照办：最近回执仍是 pending 且 remaining_seconds/deadline 等字段单调变化 → 目标事实尚未『已核』，守卫不适用；一句话声明后原样继续轮询，不改参数、不换措辞、不插入额外探索或每轮记账。终态回执即使传输标签为 [状态: failure]，也以任务书指定字段（completed/qualification）为唯一完成事实。回执字节级稳定且终态谓词已满足才是真重复，才停。
aliases: 轮询被repeat_guard拦了要不要停, 守卫说重复探索但审查还在pending, remaining_seconds还在变算重复吗, wait status循环守卫报警继续等, 异步门禁轮询被反重复守卫误拦, review没跑完守卫劝停怎么办
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:86ca7442-06e9-411f-8c2a-c3d16e3e5198:0:a004f825426bf5bc65f2
evidence_refs: learning:learn:a5e2565330f1
created_at: 2026-11-08T21:18:15.539869+08:00
updated_at: 2026-11-08T21:18:15.539869+08:00
---
## Trigger
任务书明确规定的 wait→poll 轮询协议执行中，环境 repeat_guard/反重复守卫对相同调用形状报警并劝停，而轮询目标（异步审查/门禁/子代理）尚未到达终态

## Discriminator
最近一次回执的内容可变性：state=pending 且 remaining_seconds/deadline 单调递减 = 在途过程查询，守卫的『该事实已核』前件为假；回执字节级相同且终态谓词已满足 = 真重复，守卫正确

## Short path
- 开轮询前先落一行 task_state 账本：协议参数 + 唯一终态谓词（哪个字段算完成事实）+ child_id，既满足守卫的记账建议又不在中途打断节奏
- 守卫报警时只做一次前件审计：读最近回执——pending 且预算字段在变 → 守卫条件不成立，原样继续 wait→status，保持调用形状与参数不变
- 不因守卫而换措辞、降频或插入探索性调用；轮询本身就是对『终态何时到达』这一明确未知量的逐步收缩
- 终态回执到达即停：按 qualification/completed 等字段裁决后续（如 fail-closed 不消费资格），传输 success/failure 标签不改变协议；随后才做 SHA 逐字符核验与收口

## Stop conditions
- 终态谓词满足（completed 且 qualification 等判别字段已出现）
- 回执连续完全相同、无任何变化字段（真重复：记账并停止）
- 超出 deadline/attempts 预算或任务书规定的等待/次数上限

## Verification
- 终态回执字段与任务书谓词逐项核对，指纹（candidate_sha256 等）逐字符比对，正文 VERDICT 与 qualification 一致
- 复盘轮询序列：调用形状未漂移、无协议外副作用、无因守卫报警触发的中途弃检或换道

## Counterexamples
- 终态已返回后仍重复发起同一 status 查询：守卫正确，应记账并停止
- 无终态谓词的自发重复读取（反复读同一未变文件/同一搜索）：守卫是在纠正策略，应换方法而非硬闯
- 守卫拦截的是带副作用的重复写/执行调用：必须停，与只读轮询性质不同
- 任务书未规定轮询而模型自行加轮：报警即应回到任务书，而非给轮询辩护
