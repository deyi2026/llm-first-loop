---
title: test_m3_four_buckets 满负载 CI 偶发红：_wait_tool_started 3s 观测窗口不足（非合并回归）
scenario: GitHub Actions 满负载 runner 上，全量 pytest（约 7800 个测试）跑完后 Phase4 时序测试偶发红，需判定是否合并引入的回归
root_cause: ""
solution: "判定流程（本次全链已验证）：1) gh run view --log-failed 定位唯一失败样本及断言点；2) [m3dbg] 逐样本日志区分\"机制断言失败\"vs\"脚手架等待超时\"；3) 对比合并分支改动面（git show --stat）与失败测试依赖，零交集即排除直接因果；4) 查同测试在合并前基线 run 的失败历史（gh run list --branch main + 逐 run --log-failed grep FAILED）；5) 本地低负载重跑（PHASE4_M3_REPORT_DIR 指向 /tmp 避免弄脏工作树）通过则佐证 flaky。修复：把观测窗口型 assert 的 timeout 放宽（3s→10s，与 _wait_tool_done 对齐）或改为有界重采样，勿建立在子进程 spawn 调度运气上。"
evidence: "gh run view 39805524105 --log-failed（唯一 FAILED=test_m3_four_buckets，assert False=_wait_tool_started(execute_command,_active_procs)，natural_boundary#5，[m3dbg] 前4样本ok；1 failed/9972 passed）；git show --stat e56967d9d/40d709100/c6c5e30fb 改动面零交集；run 39689641019（320f9ef23，合并前）同测试已红（idle hit=2/5）；本地重跑 job-6465c5a5d61246d8b5a6 exit=0 \"1 passed in 24.31s\""
tags: [ci-flaky, github-actions, pytest, phase4, timing, gate]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-23T00:02:01.016330+08:00"
updated_at: "2026-10-23T00:02:01.016330+08:00"
---

CI run 39805524105（main 5a570370f，2026-10-22）门禁唯一失败：tests/phase4/test_m3_bucket_metrics.py::test_m3_four_buckets，1 failed / 9972 passed。失败点=tests/phase4/test_m0_scenarios.py:98 _wait_tool_started(engine,'execute_command','_active_procs')，默认 timeout=3.0s、5ms 轮询，等待真实子进程 spawn+注册；natural_boundary 桶第 5 样本超时（前 4 同构造样本正常，[m3dbg] 日志佐证）。与三分支合并（e56967d9d/40d709100/c6c5e30fb）无关：改动面零交集（test_archive_store_durability.py、review_host_admission.py 注解、ci.yml+test_linux_installer_scripts.py）。同测试在合并前基线 320f9ef23 的 run 39689641019 已红过一次（idle 桶命中不足，当时已改补采样机制修复），本次是同测试另一处时序脆弱点。本地重跑 24.31s 通过（uv run --no-sync pytest，PHASE4_M3_REPORT_DIR 指向 /tmp）。修复方向：_sample_run 调用点把锚点等待 timeout 提到 10s（与 _wait_tool_done 对齐）或失败样本有界重采样，与 idle 桶修复同思路——机制验收不建立在 3s 观测窗口的调度运气上。注意：门禁 job pytest 失败即退出，ruff/pyright 步骤不会执行，需在报告/闸门中区分。