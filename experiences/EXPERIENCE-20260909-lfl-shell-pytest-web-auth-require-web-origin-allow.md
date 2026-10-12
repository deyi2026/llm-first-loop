---
title: LFL 会话 shell 中跑 pytest 前必须剥离 WEB_AUTH_REQUIRE/WEB_ORIGIN_ALLOWLIST（假 503 大面积失败）
scenario: 在 LFL 运行环境的 shell 中执行 llm-first-loop-mirror 的 pytest（尤其 tests/web/*）
root_cause: ""
solution: 用 env -u WEB_AUTH_REQUIRE -u WEB_ORIGIN_ALLOWLIST -u WEB_HOST 剥离继承的鉴权环境变量后再跑 pytest；503 = 环境泄漏 fail-closed，不是代码回归
evidence: 2026-09-09 worktree webui-live-parity-20260909：不剥离时 tests/web 40+ FAIL；env -u 剥离后 44 passed exit=0
tags: [pytest, env-leakage, llm-first-loop, fail-closed, web-auth]
source: {}
status: active
created_at: "2026-09-09T17:52:16.273365+08:00"
updated_at: "2026-09-09T17:52:16.273365+08:00"
---

## Gotcha
在 llm-first-loop-mirror 的 LFL 会话 shell 中跑 pytest tests/web/* 会大面积 FAIL（503 Service Unavailable），根因是 LFL web 进程环境导出了 WEB_AUTH_REQUIRE=1 与 WEB_ORIGIN_ALLOWLIST，被 auth_required() 判定为需要鉴权且未配置凭据 → require_api_key fail-closed 503。tests/web/test_frontend.py::test_api_info_returns_json 等 40+ 项会假失败。

## 正确做法
env -u WEB_AUTH_REQUIRE -u WEB_ORIGIN_ALLOWLIST -u WEB_HOST <python> -m pytest ...

## 佐证
剥离变量后同一套 44 项定向测试 44 passed / 0 failed / exit=0；同一命令不剥离则 503 大面积失败。