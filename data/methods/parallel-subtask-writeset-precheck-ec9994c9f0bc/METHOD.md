---
method_id: parallel-subtask-writeset-precheck-ec9994c9f0bc
name: parallel-subtask-writeset-precheck
description: 派发并行子任务组（spawn_subagent 多个 / workflow_run 并行或 DAG 同层）前，列出各任务写集/读集，做写写交集与读写依赖两项判定，均空才并行；否则串行化或加依赖。配套结算双闸兜底。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:54ba6da3-7041-4b6f-8aac-8df1e542850f:332:7b75e88492a9d498b9c1
evidence_refs: docs/design-subagent-borrow-mechanisms.md,experience:EXPERIENCE-20260924-edit-parallel-worktree-baseline,experience:EXPERIENCE-20261018-子代理评测实验-并发共享任务目录导致条件污染与答案泄漏
freshness_refs: docs/design-subagent-borrow-mechanisms.md
created_at: 2026-10-22T22:43:52.497383+08:00
updated_at: 2026-10-22T22:43:52.497383+08:00
---
# 并行子任务派发前写集/读集交集预检

## 触发
即将派发 ≥2 个并行子任务（spawn_subagent 多个，或 workflow_run parallel / DAG 同层）时，派发前必须完成本预检。纯只读任务写集=∅，天然可并行，但读集仍须过判定 2。

## 步骤
1. 为每个子任务列 {写集, 读集}：
   - 写集 = 预计创建/修改的路径集合（可目录级粗粒度，假阳性只导致保守串行，不致事故）
   - 读集 = 需要读取且由本组其他任务产出的路径（外部既有文件不计入）
2. 判定 1（写写）：两两写集求交；非空 ⇒ 串行化或 depends_on 排序。
3. 判定 2（读写）：任务 B 的读集 ∩ 任务 A 的写集 ≠ ∅ ⇒ B 排在 A 之后。
4. 两项均空才并行派发；判定结果记入 task_state（>10 个子任务记摘要：谁与谁冲突、如何排序）。
5. 派发说明向用户呈现：任务 | why | 权限(requires) | 写集/读集摘要 | 判定结果。

## 失败处置
- 组内单点失败：已完成子任务产物保留，失败项单独重试或收回主任务，不回滚整组。
- 重试沿用原写集；产物路径改变 ⇒ 视为新任务重新预检。
- 冲突已发生（漏检/越界写）：以 git 基线/备份区分各写者版本、逐版本判存，不自动合并，交裁决。
- 依赖失败传导：判定 2 产生的依赖链上游失败 ⇒ 下游标 blocked，不允许带空输入继续。

## 结算兜底（双闸第二闸）
子任务结算时以磁盘事实（非自报）对比"实际产物 vs 声明写集"：路径重复 ⇒ 冲突漏检，走失败处置；出现声明外新产物 ⇒ 越界写，记教训并修正该类任务写集估计。对比范围=主工作区（含已合并产物）；fs_isolation 任务按合并回主区后才纳入，隔离区同名路径不构成冲突。

## fs_isolation 合并时序
合并阶段串行执行；每个合并前将该任务写集与主区当前状态（含已合并任务的写集）再判定一次。

## 权衡
预检成本（列表+求交）≪ 并发冲突事故成本；宁假阳性保守串行。O(n²)，n<20 无瓶颈；DAG 只在同层并行组内判定，跨层由依赖边保证。

来源：docs/design-subagent-borrow-mechanisms.md v0.3 §3；配套事后教训 EXPERIENCE-20260924-edit-parallel-worktree-baseline、EXPERIENCE-20261018-子代理评测实验-并发共享任务目录导致条件污染与答案泄漏。
