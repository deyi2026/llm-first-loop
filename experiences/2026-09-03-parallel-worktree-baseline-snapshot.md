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
