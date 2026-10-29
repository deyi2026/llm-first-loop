---
title: web 鉴权 fail-closed 503 的现行边界——直接 loopback 请求已豁免，仅非 loopback/带代理头请求仍拦
scenario: 在 LFL 运行环境的 shell 中跑 llm-first-loop-mirror 的 web 测试或本地起 web 服务调试鉴权行为，遇到 503/鉴权失败需要判定是环境泄漏还是代码回归时
root_cause: ""
solution: 先判请求类别再定因：直接 loopback 请求（host+peer 均 loopback 且无 forwarded/x-forwarded-* 头）已被 request_is_trusted_local() 豁免，WEB_AUTH_REQUIRE=1 且无凭据下 pytest 直连不再 503——旧卡「跑 web 测试前必须剥离鉴权变量」的普适前提已不成立；仅非 loopback host 或带代理头的请求仍 fail-closed 503（环境泄漏表现），且启动期 validate_auth_require() 会在 WEB_AUTH_REQUIRE=1 无凭据时拒绝启动并给出明确报错。遇 503 先核请求是否过代理/非 loopback，再核环境变量。
evidence: "2026-10-29 R4 周检实测：①`env -u WEB_API_KEY -u WEB_LOGIN_PASSWORD_HASH WEB_AUTH_REQUIRE=1 .venv/bin/python -m pytest tests/web/test_frontend.py -q` → 7 passed in 0.39s（完整 fail-closed 条件下无 503）②src/llm_loop/web/auth.py:124-126 `request_auth_required()` = `auth_required() and not request_is_trusted_local(request)`③bypass 引入 commit 7d134bbee（2026-09-30 fix(web/auth): bypass auth only for direct loopback）④auth.py:98-122 request_is_trusted_local：loopback host+peer 且无 forwarded/x-forwarded-* 头才豁免。"
tags: [web-auth, 503, loopback-bypass, fail-closed, pytest, boundary]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T20:06:54.830828+08:00"
updated_at: "2026-10-29T20:06:54.830828+08:00"
---

## 适用信号
在 LFL 会话 shell 跑 llm-first-loop-mirror 的 web 测试（pytest tests/web/*）或本地调试 web 鉴权，见到 503 / 鉴权失败时——先按现行边界定位请求类别，再判断是否环境泄漏。

## 不管什么
不管「跑 pytest 前必须剥离 WEB_AUTH_REQUIRE/WEB_ORIGIN_ALLOWLIST」这一旧前提：直接 loopback 请求（pytest TestClient 默认形态）已被豁免，剥离不再必要。也不管非 web 场景的 env 泄漏（那是 EXPERIENCE-20260909-lfl-llm-pytest-tail 的管辖面）。

## 核验方法
1. `env -u WEB_API_KEY -u WEB_LOGIN_PASSWORD_HASH WEB_AUTH_REQUIRE=1 .venv/bin/python -m pytest tests/web/test_frontend.py -q` → 期望 7 passed（直接 loopback 豁免，不出现 503）。
2. `sed -n '124,126p' src/llm_loop/web/auth.py` → 期望 `request_auth_required()` 返回 `auth_required() and not request_is_trusted_local(request)`。
3. 非 loopback / 带 forwarded 头的请求（WEB_HOST 非 loopback 或 x-forwarded-for 非空）→ 仍 fail-closed；启动期 `validate_auth_require()` 校验仍在。

## 核验记录
- 2026-10-29（R4 周检落卡）：核验点 1 实测 7 passed；核验点 2 摘录一致；bypass 由 commit 7d134bbee（2026-09-30）引入。本卡替代 experience:EXPERIENCE-20260909-lfl-shell-pytest-web-auth-require-web-origin-allow（同日按 R3 事实轴 invalidate，理由见该卡 note）。