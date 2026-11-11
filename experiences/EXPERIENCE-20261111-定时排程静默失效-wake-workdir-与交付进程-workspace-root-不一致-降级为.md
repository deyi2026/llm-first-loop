---
title: 定时排程静默失效：wake_workdir 与交付进程 workspace_root 不一致 → 降级为待授权通知后无人执行
scenario: LFL 周期排程（定时发表文章等 task_recurring+wake）连续多个班次未执行，但排程表里 trigger_at 正常推进、无报错、无失败告警；审计里只有 degraded_to_notify「工作目录与授权时不一致（拒绝在新目录执行）」。典型触发：服务被重部署到 .releases/<sha> 的 release 目录（service_control 启动时 LFL_WORKSPACE_ROOT=code_root、cwd=runtime_root），而排程签发时按会话 current_workspace_root 钉下的 wake_workdir 是 runtime 根。交付判据是 os.path.realpath(entry.wake_workdir) != os.path.realpath(交付进程 workspace_root)，两者一旦分叉就永远拒绝执行。
root_cause: ""
solution: "排查入口（三步）：1) data/schedule.json 逐条看 sid/wake_workdir/trigger_at/count/wake_owner_pid——trigger_at 已推进且无对应产物=已空跑；2) data/audit/action_trace.jsonl 过滤 \"phase\": \"schedule.wake\" 与 action_type=degraded_to_notify，看 reason 是否为目录不一致（区分于 runner_admission_failed）；3) 对比交付进程实际 workspace_root（runtime_manifest.*.json 的 workspace_root / 进程 cwd）与排程钉的 wake_workdir。修复方向：A 清掉抢占 claim 的旧实例（多区共用同一 schedule store 时，旧进程会抢走 claim 并按自己目录判定）；B 重新签发排程，使 wake_workdir 与交付方 workspace_root 一致（注意 schedule 工具只能钉当前会话的 current_workspace_root，不能手填路径）；C 改判据让 release 目录与 runtime 根等价（发版免疫，需代码修复+发版）。降级通知不会自动执行（R8.13 需真人授权），web 侧只做 observed_only，因此这类失效是静默的，必须靠审计查。当前性验证（改动后先跑这两条再套用本卡结论）：(a) grep -n 'realpath(entry.wake_workdir)' src/llm_loop/core/schedule_delivery.py —— 应仍命中一条（判据未被改动）；(b) grep -h '\"phase\": \"schedule.wake\"' data/audit/action_trace.jsonl | grep degraded_to_notify | tail -5 —— 应能看到 reason=工作目录与授权时不一致；若这两条任一变化，本卡的失效链结论必须重新核对而不是直接复用。"
evidence: "2026-11-11 实测：data/audit/action_trace.jsonl 三条 degrade 记录——2026-11-10T13:00:03 sched-a6287020、2026-11-10T20:00:04 sched-3e4a1e65、2026-11-11T08:00:03 sched-8ddf6df8，reason 均为「工作目录与授权时不一致（拒绝在新目录执行）」；对应 docs/promotion 最新产物止于 20261110（daily-76），20261111 无产物；data/schedule.json 中三者 wake_workdir=<REPO> 而 trigger_at 已推进到次日；判定逻辑见 src/llm_loop/core/schedule_delivery.py:152-154（realpath 比对）与 deployed release .releases/7b5b0848 同逻辑；service_control.py:3490 启动时注入 LFL_WORKSPACE_ROOT=code_root、cwd=deployment.runtime_root（:3540/:3547）；schedule.py:445 按 current_workspace_root 钉 wake_workdir。"
tags: [scheduler, schedule, wake, workdir-binding, deployment, silent-failure]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-11T10:57:26.844696+08:00"
updated_at: "2026-11-11T10:57:26.844696+08:00"
---