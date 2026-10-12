---
title: "Cloudflare tunnel 双主机名同源部署的登录循环:host-only cookie 分裂"
scenario: "Cloudflare Named Tunnel 多主机名指向同一源站的 Web 服务,浏览器登录状态在主机名间分裂,表现为\"密码对但反复弹登录页\""
root_cause: ""
solution: "WEB_SESSION_COOKIE_DOMAIN 配置父域 cookie 共享;诊断时用\"POST 后紧跟 GET 的状态码对\"识别;日志无 Host 头,可用 curl 逐域对比或 tcpdump 抓 Host"
evidence: web.log 中 POST /auth/login 303 + GET /ui/v2/ 303 循环记录;tests/web/test_login_cookie_domain.py 32 passed
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-30T12:45:59.957041+08:00"
updated_at: "2026-09-30T12:45:59.957041+08:00"
---

llm-first-loop web 经 Cloudflare tunnel 暴露两个主机名(llmfirstloop.com 与 app.llmfirstloop.com)到同一源站 127.0.0.1:8903。登录 cookie 默认 host-only,浏览器按主机名各存一份 → 用户在两域间切换(书签/历史)时反复弹回登录页。服务端日志特征:POST /auth/login 303(密码正确)紧跟 GET /ui/v2/ 303(该主机名无有效会话)循环;同一用户 favicon.svg 200/303 交替(两域一有一无)。修复:新增 WEB_SESSION_COOKIE_DOMAIN=llmfirstloop.com,login()/logout() 的 set_cookie/delete_cookie 带 domain=session_cookie_domain();回归测试 tests/web/test_login_cookie_domain.py(注意 TestClient cookie jar 按 testserver 域匹配,断言 Set-Cookie 原始头而非 resp.cookies)。