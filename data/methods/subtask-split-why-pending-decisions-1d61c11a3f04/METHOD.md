---
method_id: subtask-split-why-pending-decisions-1d61c11a3f04
name: subtask-split-why-pending-decisions
description: 派发子任务时强制写 why（须能回答"不拆的代价"），派发说明用固定表格（任务|why|权限|写读集|判定结果）；"值不值得做只有用户知道"的开放项聚合为待裁决队列集中呈现，每项带选项与默认行为。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:54ba6da3-7041-4b6f-8aac-8df1e542850f:332:7b75e88492a9d498b9c1
evidence_refs: docs/design-subagent-borrow-mechanisms.md
freshness_refs: docs/design-subagent-borrow-mechanisms.md
created_at: 2026-10-22T22:44:06.098572+08:00
updated_at: 2026-10-22T22:44:06.098572+08:00
---
# 子任务拆分理由透明化 + 待裁决项聚合

## 拆分 why（派发时强制）
spawn 子任务时，除已有必填 acceptance 外，强制写明 why：为什么这个子任务值得单独拆出（一句话预期收益），必须能回答"不拆的代价是什么"。
- 写不出"不拆的代价" ⇒ 拆分理由不成立，默认不拆，并入主任务执行。

## 派发说明固定格式
并行派发时向用户呈现统一表格：**任务 | why | 权限声明(requires) | 写集/读集摘要 | 判定结果（并行/串行原因）**。
- 写集为空的纯读任务优先声明 fs_isolation 或最小 fs 权限（权限最小化，防并行任务默认全 fs 写权限）。

## 待裁决项聚合
1. 子任务产出中"值不值得做只有用户知道"的开放项，聚合为待裁决队列，在回复中以固定段落集中呈现，不散落在各子任务汇报里。
2. 每项必须附带选项与默认行为（不裁决时我方按什么继续），不允许只抛问题。
3. 裁决后队列项标记已裁决并回填结果，不重复请示；无新事实不复议。

当前性验证：grep -n "待裁决\\|why" docs/design-subagent-borrow-mechanisms.md 应命中 §5（约 95-111 行），确认机制三行为定义仍在；若文档已重构/移除，先重读本节再沿用。

来源：docs/design-subagent-borrow-mechanisms.md v0.3 §5。
