---
title: 写进 durable 账本的 commit sha 必须先取 git log 回执，不能凭会话记忆
scenario: 长会话多处提交后，把 commit sha 写进 goal checkpoint 与 evolution 执行登记；事后发现其中一项 sha 不存在、另一项指向后续 polish 提交而非主实现
root_cause: ""
solution: 写账本 sha 前先取 git log 回执并按路径逐笔核对；发现错误时优先在仍可写的账本更正，若已 complete 则落 lesson 记正确溯源并在交付答复中显式披露差异
evidence: git log --oneline -- src/llm_loop/tools/review_report.py（d852cf09d/4fba59da5/557f09051）、-- src/llm_loop/tools/review_host_admission.py（9ddf748ce）、-- tests/unit/test_review_report_persistence.py、-- tests/test_catastrophic_data_payload.py（f36083fc9）；git rev-parse HEAD=a204a22f6；commit 96ecbd9fb 经 git log 检索不存在
tags: [记录诚实, commit-sha, goal-checkpoint, evolution-log]
source:
  session: bc422278-b7a4-4c97-9380-4dc56a6da24f
  goal: GOAL-20261101-4dc5c8bf
  evo: EVO-20261101-86e754fc
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-01T20:27:05.157938+08:00"
updated_at: "2026-11-01T20:27:05.157938+08:00"
---

事实：EVO-20261101-86e754fc 的正确溯源如下（git log --oneline 回执）：主实现 9ddf748ce；P1 symlink 预植修复 557f09051；0700/fd/P10 修正 4fba59da5；timekeeping 修正 d852cf09d；安全探针 f36083fc9；HEAD 与发布 = a204a22f6。

错误：我在 checkpoint_goal 与 evolution_complete(actions[].evidence) 里把主实现写成 4fba59da5，把安全探针写成 96ecbd9fb（该 sha 在本仓不存在）。发现时 goal 已置 complete，checkpoint 无法追加，evolution_exec 亦无修订入口，只能口头更正——错误引用已进入可检索账本。

可复用判据：
1. 任何写入 durable 账本（goal checkpoint / evolution actions / task evidence）的 commit sha，必须先跑 `git log --oneline -n -- <path>` 或 `git log --oneline -N` 取回执，禁止凭"我记得刚提交过"填。
2. 一次会话内多次提交后，引用前重新取 log；同一 EVO 分散在多笔提交时，逐笔按文件路径取，别用 HEAD~N 心算。
3. 若目标已 complete 才发现记录错误：不要伪造"已更正"，改为在 lesson/experience 落正确溯源并在交付答复里显式说明差异，让后续读者以 git 为准。