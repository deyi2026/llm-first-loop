---
title: 并行写者共享工作树：开工先留基线，edit 失配先三版本对比再动手（parallel-worktree-baseline）
scenario: 主会话对 tool_cycle.py 的实施被并行演进管线半途覆盖（工作树出现半成品混合态：部分块已替换、部分未动），再次开工时 edit 失配。后续 spec 子代理线（tool_loop_guard）与主会话、经验线同时改同一仓库，factory.py 混入两线改动。
root_cause: 多个写者（主会话 / 演进管线 / spec 子代理）无协调共享同一工作树；滞后读取的工作树状态被当作现状使用。
solution: "开工前 git status --porcelain + 关键文件行数/hash 留底；edit 失配时先做三版本对比（HEAD / index / worktree）判断\"谁改了什么\"，再决定收编/回退/继续，禁止基于记忆中的旧状态盲改；发现他线半成品先评估语义再动手（spec 线按 design D9 判定先行实现为被否决方案，走\"收编改写\"而非\"原样继续\"），处置记录进 tasks §0 现状校准表。"
evidence: "原始收据（2026-09-03 时点核验，原文件 git 跟踪在库）：1) .codeartsdoer/specs/tool_loop_guard/tasks.md §0 先行实现收编四项差异；2) EVO-DRAFT-loop-breaker-task-restart-guard.json（管线半成品落盘先例）；3) factory.py 双线共存验证（experience 注入行 + loop_guard route_fn 接线）。2026-09-24 收编时点复验：tasks.md §0 现存（53,627 字节，Sep 3）；EVO-DRAFT json 与 factory.py loop_guard 接线在当前 HEAD 已不存在（后续演进移除，属历史时点证据，不影响本条作为操作纪律的成立）。"
tags: [parallel-writers, worktree, git-baseline, edit-conflict, coordination]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-24T16:29:41.146360+08:00"
updated_at: "2026-09-24T16:29:41.146360+08:00"
supersedes: [EXPERIENCE-20260903-untitled]
---

# 经验：并行写者共享工作树时，开工先留基线、失配先三版本对比

## 场景
主会话对 tool_cycle.py 的实施被并行演进管线半途覆盖（工作树出现半成品混合态：部分块已替换、部分未动），再次开工时 edit 失配。后续 spec 子代理线（tool_loop_guard）与主会话、经验线同时改同一仓库，factory.py 混入两线改动。

## 根因
多个写者（主会话 / 演进管线 / spec 子代理）无协调共享同一工作树；滞后读取的工作树状态被当作现状使用。

## 解法
- 开工前 `git status --porcelain` + 关键文件行数/hash 留底；
- edit 失配时先做三版本对比（HEAD / index / worktree）判断"谁改了什么"，再决定收编/回退/继续，禁止基于记忆中的旧状态盲改；
- 发现他线半成品先评估语义再动手：本次 spec 线按 design D9 判定先行实现为被否决方案，走"收编改写"而非"原样继续"，处置记录进 tasks §0 现状校准表。

## 证据
- .codeartsdoer/specs/tool_loop_guard/tasks.md §0（先行实现收编四项差异）
- EVO-DRAFT-loop-breaker-task-restart-guard.json（管线半成品落盘先例）
- factory.py 双线共存验证（experience 注入行 + loop_guard route_fn 接线）

---
[收编记录] 2026-09-24 由孤儿文件 experiences/2026-09-03-parallel-worktree-baseline-snapshot.md 原文全量收录（该文件未被 ExperienceStore 命名规范覆盖，无法检索）；原件 git HEAD 仍在库，工作树已移除。