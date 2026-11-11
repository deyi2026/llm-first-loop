---
title: 排程静默空跑根因＝同区多进程抢 claim + 工作区漂移（非 release 目录），修法＝R7 降级改退避让位
scenario: "2026-11-11：定时发表文章任务连续三个班次（11-10 13:00、11-10 20:00、11-11 08:00）静默未执行，trace 只有 degraded_to_notify(workdir_mismatch)，无报错无产出；发版后当天 13:00 午班必须实测跑通。"
root_cause: ""
solution: 根因＝同区多进程共享 schedule store，非权威进程（CLI 以 --workspace 临时 goal worktree 启动）抢到 claim 后按自身 workspace 判定 R7 目录不符 → 直接降级通知并消费掉该次触发（R8.13 通知需真人授权→静默跳过）。修复＝R7 分支 degrade 改 defer（退避让位，不消耗额度、不发通知，让同区能兑现钉死目录的进程接管；让位预算耗尽才降级通知）。配套：停掉漂移的孤儿进程；用 standing 探针（task_recurring+repeat_interval+wake_fires）实测 action_type=started 验证投递链路；只有 web 服务起调度线程，进程存活可用 schedule.json mtime 每 10s 变化判断。
evidence: "trace: data/audit/action_trace.jsonl 中 instance=<HOST>.local-6209 的 degraded_to_notify(workdir_mismatch) ×3（11-10 13:00/20:00、11-11 08:00）；探针 sched-04053355 于 11:16:37 action_type=started session=9c0eaab5-…（web 服务 claim，证明投递链路通）；修复 commit e2bbaf3a0，review_admission PASS，全量门禁 job-08ba2d7d42e74bc8973c exit=0；发版 desired generation 405 / git_head e2bbaf3a0"
tags: [scheduler, schedule, workdir_mismatch, multi-process, silent-skip, R7, delivery]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-11T11:42:49.787582+08:00"
updated_at: "2026-11-11T11:42:49.787582+08:00"
supersedes: [EXPERIENCE-20261111-定时排程静默失效-wake-workdir-与交付进程-workspace-root-不一致-降级为]
---

现象：连续多个班次的定时排程未执行，无报错；action_trace.jsonl 里只有 schedule.wake / degraded_to_notify（workdir_mismatch）。

定位路径（可复用）：
1. 按「谁写的这条 trace」追：action_trace 的 instance 字段 = hostname-pid → 用 lsof -a -p <pid> -d cwd 拿进程 cwd，用 lsof -p <pid> 看 txt/cmdline 拿启动参数。调度事件的 instance 才是真正抢到 claim 的进程，不是你以为的服务进程。
2. 判定 R7：schedule_delivery.__call__ 比较的是 entry.wake_workdir（授权时钉死）与本进程 build_engine 的 workspace_root（= 启动参数 --workspace，未给则 Path.cwd()）。二者 realpath 不等即 workdir_mismatch。
3. 关键结构事实：同区多进程共享同一 schedule store（同一 DATA_DIR），非权威进程可以抢到 due entry 的 claim；随后它用自己的 workspace_root 判定「目录不符」→ 降级为通知并消费掉该次触发；R8.13 通知需真人授权 → 表现为静默跳过、无产出。
4. 只有 web 服务起调度线程（web.log「调度提醒线程已启动 tick=10.0s」）；feishu/learning/wecom 不起。schedule.json 的 mtime 每 ~10s 变化 = 调度线程活着（可作为存活探针）。
5. 进程 workspace_root 漂移的常见来源：以 --workspace <临时 goal worktree> 启动的交互式 CLI（例如 lfl chat --interactive），它的 cwd 仍是仓库根但 engine workspace_root 是临时 worktree。

修复（已发版）：R7 分支由 _degrade 改为 _defer("workdir_not_eligible_owner")——释放 lease、不消耗额度、不发通知，退避让位给同区能兑现钉死目录的进程；让位预算（WAKE_MAX_RETRIES=10 / WAKE_RETRY_WINDOW_S=1800）耗尽仍无人兑现才降级通知（可见不静默）。仍然禁止在非钉死目录执行。

验证纪律：不要只看 trace 推断投递链路可用。注册一个 standing 探针（task_mode=task_recurring + repeat_interval>0 + wake_fires≥1 + wake_workdir=当前根）观察 action_type 是否为 started（真开新会话）；task_once/task_reminder 不是 standing，不会触发 wake 投递。发版/重启后靠 ledger 授权 recovery 接管（web.log「wake delegation recovered before due」）。

坑：arch guard 有函数行数 ratchet（≥120 且未登记即红）；改函数时注释行也算，会把 CI 门禁打红（RULE-AI-32 hunk 级最小化的另一个约束）。