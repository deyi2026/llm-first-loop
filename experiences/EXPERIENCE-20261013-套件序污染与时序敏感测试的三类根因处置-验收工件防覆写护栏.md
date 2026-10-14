---
title: 套件序污染与时序敏感测试的三类根因处置 + 验收工件防覆写护栏
scenario: 多用例套件下时序敏感测试（异步 worker/共享单例/全量回归负载）的失败定位与验收工件一致性保障
root_cause: ""
solution: 断言消息携带状态现场做一次取证；用事件锚定替代固定时延构造；验收工件写入加防覆写护栏。
evidence: Phase4 GOAL-20261013-9b1fa766 M4：test_d 经 4 轮错误假设后由断言内嵌现场取证定位真因（worker 轮1 消费竞速）；unit 前缀复现 7575 绿+全套 8225 绿回执；终局评审以 M3_ACCEPTANCE.json 实值揭穿报告数字漂移（工件无护栏被覆写）。
tags: [testing, race-condition, test-pollution, evidence-driven-debugging, acceptance-artifacts]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T12:26:26.532996+08:00"
updated_at: "2026-10-13T12:26:26.532996+08:00"
---

全量回归（8200+ 用例）下单测隔离恒绿但套件必挂的三类根因与修复模式：
①上下文泄漏（contextvar/单例残留）→ 登记侧显式重置到用例语义值（如 current_run_generation.set("")）；
②worker 时序竞速（主线程 enqueue 先于 worker 轮首消费）→ 事件锚定：被测前置事实发生（工具 started Event）后再触发用例动作，杜绝固定 sleep；
③全局 mock 泄漏（time.sleep 被 patch）→ 保活构造用锁原语（threading.Event.wait）替代可 mock 的阻塞。
取证纪律：断言消息内嵌四分量现场（handle status/pending/cancel/unsettled），一次失败即拿到分量为证，胜过 N 轮盲跑重试。
配套教训：验收工件（reports/*.json）写入必须默认防覆写（PHASE4_OVERWRITE_REPORTS=1 才强制），否则调试重跑会静默漂移已写入交付报告的数字。
当前性验证：grep -n "PHASE4_OVERWRITE_REPORTS" tests/phase4/test_m3_bucket_metrics.py 应命中护栏行；.venv/bin/python -m pytest tests/phase4/test_m2_inflight_interrupt.py -q 应 6 passed。