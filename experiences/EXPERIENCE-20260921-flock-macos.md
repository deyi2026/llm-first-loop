---
title: 同进程 flock 不互斥（macOS）：跨进程锁测试须用真实子进程持锁
scenario: "为跨进程互斥原语（flock 文件锁）写单元测试：被测函数探测\"别的持有者\"，而测试只能运行在同一进程内。"
root_cause: ""
solution: 持锁方必须用真实子进程模拟（Popen 持锁+回执+stdin 退出信号）；先写孤立双进程复现脚本确认 flock 语义，再落测试；持锁路径/探测路径必须取同一常量，防误用相邻路径函数导致假失败。
evidence: tests/unit/test_learning_idle.py（_LOCK_CHILD 子进程持锁器，5/5 passed）；/tmp 孤立复现脚本输出（parent blocked expected）
tags: [flock, cross-process, testing, macos]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-21T00:28:33.851070+08:00"
updated_at: "2026-09-21T00:28:33.851070+08:00"
---

现象：learning_idle 的 consumer_active() 用 flock 探测另一"进程"是否持锁，单元测试先在测试进程内 open+flock 模拟持锁方，探测方（同进程另一 fd）总能抢到锁，测试失败。定位：macOS/Linux 的 flock 冲突判定在 macOS 上按进程（同进程两个 fd 不互斥），与生产"控制 worker 进程探测、learning 消费进程持锁"的跨进程形态不符。修复：测试持锁器改为真实子进程（Popen python -c 持锁后 print held、stdin.readline 等待退出信号），断言 held 后测 True、退出后测 False。孤立复现脚本（/tmp 下父进程 BlockingIOError）先行确认了 flock 跨进程语义本身正确。另注意测试持锁路径要用 consumer_lock_path() 而非误用 journal_path()（曾因此假失败）。