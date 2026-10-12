---
method_id: enumerate-task-surface-via-matching-commit-stat-before-path-guessing-660835bf0587
name: enumerate-task-surface-via-matching-commit-stat-before-path-guessing
description: 执行明确范围的任务（尤其标为“余项/续作”）时，若 git log 中已显示一条提交消息覆盖同一阶段/子系统，就用 `git show --stat <hash>` 作为权威文件清单来源，替代按文档里模块名去猜相对路径的 ls/find。仓库实际根前缀（如 src/…）与 vendored/venv 目录会让路径猜测落空、find 沦为 site-packages 噪声；commit stat 一次给出源码+测试+fixture 的精确清单，把任务转成“spec 语义 ↔ 既有实现面”的差集，只实现真正缺失的部分。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:969:70aac8e379605c9044ad
evidence_refs: learning:learn:b49bc433f62c
created_at: 2026-10-09T12:53:00.300021+08:00
updated_at: 2026-10-09T12:53:00.300021+08:00
---
## Trigger
需要定位某任务涉及的代码文件/模块；任务范围明确（spec 或任务行已点名阶段与模块），且 git log 已可见一条提交消息与该范围匹配的提交。

## Discriminator
在进入任何文件系统搜索之前就已可见的两个事实：(1) spec/设计文档行已点名目标模块名；(2) git log 已显示一条提交消息覆盖该任务范围（同阶段编号/子系统/交付关键词）并给出 hash。此时该提交的 stat 即权威清单，路径猜测式 ls/find 是冗余动作。

## Short path
- 从 goal/task 记录取任务范围与 spec_change_ref 指向的权威文档
- grep 权威文档中的任务关键词，得到点名的模块与验收语义
- 在 git log 中找消息覆盖该范围的提交，取 hash
- 直接对该提交 `git show --stat` 获得精确文件清单（源码+测试+fixture）
- 只读清单内文件的结构定义面，与 spec 语义做差集，实现真正缺失的余项
- 全量回归与 lint 验证后收口

## Stop conditions
- 已从匹配提交的 stat 获得文件清单，且与 spec 点名模块交叉一致
- 清单文件的结构读回证实消息声明的能力真实存在，差集确定
- log 中不存在范围匹配的提交——此时路径/目录宽发现才是正当下一步

## Verification
- spec 行点名的每个模块都出现在 commit stat 文件清单中
- 抽读清单内文件的定义面，确认与提交消息声明一致（防消息夸大）
- 实现后跑全量回归确认无未覆盖余项

## Counterexamples
- 全新功能，log 中无任何范围匹配提交——git-stat 捷径不存在，需常规 find/grep 发现
- 提交消息含任务关键词但 stat 文件与任务无关（关键词碰巧重合）——消息匹配不充分，退回其他定位手段
- 匹配提交之后工作区有大量未提交改动或更近提交覆盖同一模块——stat 已过期，必须结合 git status/diff 重新核对
