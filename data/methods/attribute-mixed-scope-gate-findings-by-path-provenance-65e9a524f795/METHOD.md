---
method_id: attribute-mixed-scope-gate-findings-by-path-provenance-65e9a524f795
name: attribute-mixed-scope-gate-findings-by-path-provenance
description: 委派的门禁审查（full_test等）对混合送审范围——自有任务补丁已SHA验证与此前过审候选逐字节一致＋rebase继承的main侧路径——返回非PASS终态时，第一未知量不是『怎么修』而是『每条阻断发现属于哪个子范围』。用送审前固化的两个路径集合＋补丁SHA实测，把P0/P1逐条按文件路径机械归属：若全部阻断发现落在继承路径，则失败是main侧基线问题，本会话不修不重跑不越权，向父会话报告归属分区与决策分叉（main侧另行修复后重审 vs 范围切割重审）后停在委派边界；发现触及任务路径或任务代码功能依赖被标记的继承代码时边界不干净，按普通REVISE处理或协调修复。
aliases: 审挂了先按路径定责再上报, P1全落在main侧路径怎么办, rebase候选门禁失败归属切分, 混合送审范围REVISE处理, 门禁发现不在任务路径内的上报分叉
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bad15472-ff6f-49d3-b7bc-92e35ebb3b93:0:36ec77aa6304b6eb992e
evidence_refs: learning:learn:725f0414abc9
created_at: 2026-11-09T01:01:57.169074+08:00
updated_at: 2026-11-09T01:01:57.169074+08:00
---
## Trigger
委派审查会话对混合范围候选（自有任务补丁已SHA验证与此前过审候选一致 + rebase继承的main侧路径）执行昂贵门禁（full_test类），门禁返回非PASS终态（REVISE/BLOCK）且含路径级findings

## Discriminator
verdict返回前已存在的三件事实：①任务补丁路径集与全量送审路径集已分别固化为可机械比对的清单；②补丁SHA实测值与此前独立过审候选声明值相等（自有范围回归概率已被压低）；③继承路径来自另一lane在上一轮过审之后合入main。三者把『失败归谁』缩成一次集合隶属计算

## Short path
- 核验阶段即把任务路径集与全量送审路径集分别落盘，并实测补丁SHA（分区材料先于门禁启动固化）
- 门禁非PASS终态：读完整审查报告全文，把每条P0/P1/P2映射到其文件路径
- 逐条做集合归属：任务路径 vs 继承的main侧路径（纯机械计算）
- 阻断(P0/P1)发现全部落继承路径且补丁SHA未变：不修改、不重跑、不代父会话选路线；报告『归属分区＋决策分叉（main侧另行修复后整体重审 vs 范围切割重审）』，附报告落盘路径，停在委派边界；自有路径内的非阻断发现（如P2）仍如实单列供父会话参考
- 发现触及任务路径、或任务代码import/call被标记的继承代码：边界不干净，按普通REVISE处理并显式说明依赖，不做纯升级

## Stop conditions
- 归属分区完成且决策分叉已显式移交父会话/用户，本会话不选择修复路线
- 分区依据（两路径清单、SHA实测、报告原文）均已作为可复核证据附上

## Verification
- 每条阻断finding的文件路径对两个集合的隶属关系可机械复核
- 补丁SHA实测与此前过审候选声明一致；送审scope与全量路径清单一致
- 最终报告附审查报告落盘路径与counts，不以截断回执代替全文

## Counterexamples
- 任务补丁功能依赖被标记的继承代码（如调用被删的dedup/守卫）：路径归属≠责任归属，纯升级会漏掉自身侧协调修复
- 补丁SHA与此前过审候选不一致（rebase改变了内容）：路径级归属不足，须先做内容级diff再定责
- 门禁报告只有整体verdict无路径级findings：无法分区，整体按REVISE处理
