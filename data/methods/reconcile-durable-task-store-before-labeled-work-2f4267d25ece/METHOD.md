---
method_id: reconcile-durable-task-store-before-labeled-work-2f4267d25ece
name: reconcile-durable-task-store-before-labeled-work
description: 当持久化 Goal/Task 系统与会话内计划表并行存在（两套编号共享同一前缀）时，在每个单元边界先用一次权威查询对齐编号、剩余项与状态；把持久化系统当作'还剩什么/验收口径/evidence 引用格式'的唯一权威，并在投入实现轮次之前向用户显式化任何范围分歧。
status: candidate
source_model: glm/glm-5.3
teacher_refs: method:method-self-distill-root-cause,method:method-self-distill-repo-api,method:method-self-distill-ab
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T19:17:37.943325+00:00
updated_at: 2026-09-09T19:17:37.943325+00:00
---
trigger:
  - 存在持久化任务/目标系统，且会话内另有一份带同形编号（如 T#）的平行计划表
  - 即将按会话侧编号开工新单元，或需要查询某编号的验收口径
  - 单元完成准备提交/翻状态时
discriminator:
  - 自身代码注释或近期提交已携带持久化 goal/task 标识 → 一次任务图查询即可取得权威的剩余项清单、编号语义与当前状态
  - checkpoint/事实与图状态可能漂移（事实已完成但任务未翻 done），提交回执即真值
short_path:
  1. 单元边界查一次任务图，建立 会话编号↔图编号 的显式映射（未知量：剩余项与编号语义属于哪套权威）
  2. 若发现编号冲突或会话项超出持久化目标原始范围 → 立即向用户标出分歧并请求裁决，再投入实现
  3. 查验收口径时先读任务系统原文，而不是文档关键词搜索
  4. 提交时同步翻任务状态；evidence 引用必须来自真实工具回执（按系统要求的前缀），不得编造占位符；被拒时按错误信息给出的契约改用真实回执引用
branch_on_evidence:
  - observation: 编号一一对应且状态新鲜
    next: 直接按图推进，不再额外取证
  - observation: 编号冲突或会话项超出原始目标范围
    next: 停止实现，先向用户显式化分歧
  - observation: checkpoint 与任务状态不一致
    next: 以提交/回执事实为准先修正图，再继续
stop_conditions:
  - 任务图与已提交事实一致（无 stale 状态），且所有范围分歧已向用户显式化并获裁决
verification:
  - 任务图查询显示无滞后状态；状态更新被系统接受（未被引用格式拒绝）即证明引用真实
anti_patterns:
  - 按会话编号连做多个单元、多次提交后才首次查图
  - 用占位/伪造引用填状态更新
  - 用文档关键词搜索代替任务系统查询验收定义
programizable:
  - 检测双源同前缀编号冲突、checkpoint 与任务状态漂移、evidence 引用前缀校验、commit→任务状态翻转钩子
model_owned:
  - 判断用户意图中哪套是权威、分歧是否值得停下询问、会话项与图任务的语义映射
why_shorter: 用一次权威查询替代事后跨 docs/frontier/goal/evidence 的还原取证链，并把范围分歧从收尾期提前到实现之前。
counterexamples:
  - 用户明确指定会话表为唯一计划权威、任务无持久化系统
  - 编号已 1:1 同步且状态新鲜时重复查询（用已有回执即可）
  - 单个无系统集成的独立小任务
