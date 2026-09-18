---
title: laap.cn 站内 API 直调路径（注册/聊天/免费模型代理）与 Cloudflare 指纹绕行
scenario: 复现 laap.cn（LAAP/Aris）站内注册与聊天时，直接 HTTP 调用被 Cloudflare 1010 拦截、找不到 API 基址、聊天报 session_id 无效
root_cause: ""
solution: 用 curl 而非 Python urllib（TLS 指纹）；从 bundle 提取 API_BASE_URL 为空串（同源 /api）；注册无验证码；建会话后再聊天；服务器模式聊天上游 Key 失效，改用同源 SenseNova 免费代理 /api/sensenova/v1/chat/completions
evidence: "evidence://v1/6205b912ded2b78eb52ff96bbb7dea7de5483f88603342761cf7a8b8e805ee5a; evidence://v1/9c617b0aa127f6346fa669de511376582d9384f06187548ef9dd1005b9c4811c; evidence://v1/766b037d22070c1d4ba8123221645a9068bf6a032352a68d5f526ad1e6fcff5b; evidence://v1/dd451361ef502838a2ff11a7c273fcf331c0dd6c589196501926db5189b8656d"
tags: [laap.cn, aris, cloudflare-1010, same-origin-api, sensenova, probe]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T09:51:08.553343+08:00"
updated_at: "2026-09-18T09:51:08.553343+08:00"
---

laap.cn 前端 API_BASE_URL 为空字符串 → 所有接口同源 https://laap.cn/api/...（api.kemo.ink 是另一回事，DNS 仅私有 IPv6，公网不可达）。注册 POST /api/v1/auth/register {username,email,password} 无验证码；登录态 Bearer JWT；聊天=先 POST /api/v1/sessions {title} 取 Convex id，再 POST /api/v1/chat。服务器模式 /api/v1/chat 因上游 LLM Key 失效不可用；可用的是 OpenAI 兼容免费代理 POST /api/sensenova/v1/chat/completions（sensenova-6.8-flash-lite）。Cloudflare 错误1010 封 Python urllib 指纹，curl 同参数可通过。人格/记忆为浏览器端 IndexedDB 存储（laap_local_user_id），默认人格字段全空。