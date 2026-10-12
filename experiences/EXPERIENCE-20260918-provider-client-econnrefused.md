---
title: provider client 构造时固定代理配置导致 ECONNREFUSED 永不自愈：传输失败退休缓存实例
scenario: 服务进程内某 LLM provider 全部调用瞬间 ECONNREFUSED，而同期新进程（shell/curl/子进程）访问同一端点正常；重启服务或 refresh_config 后立刻恢复
root_cause: ""
solution: 在传输级连接失败时退休该 provider/model 的缓存 client，使下次调用按当前系统代理/网络配置重建：LLMClient 加 on_transport_failure 回调（构造时由 ModelClientPool 注入 → retire_client_for），ConnectError 重试前加 0.5s 退避。退休沿用 replace_registry 语义（最后引用释放后关闭），不改重试/降级/严格模式语义。
evidence: "commit 3bf8364be（src/llm_loop/llm/client.py, src/llm_loop/llm/pool.py, tests/unit/test_model_pool_per_model.py）；活体脚本 /tmp/selfheal_live_check.py 输出（[step2] 0.51s LLMNetworkError / [step3] hook 2x ConnectError / [step5] PASS）；gen20 部署 verify ok；事故现场证据 evidence://v1/fdcbb85a0d49d663be7703ec1ec67d19c4a30c254e07094f2309b5dc6b0bcdae（refresh_config 后 GLM 3/3 成功）"
tags: [llm, httpx, proxy, surge, self-heal, connection-refused, macos-system-proxy, client-pool]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T15:44:55.412256+08:00"
updated_at: "2026-09-18T15:44:55.412256+08:00"
---

现象：服务进程内某 provider（如 glm）所有调用瞬间失败 `[Errno 61] Connection refused`，两次尝试相隔 2.8ms 同因；同一时刻 shell/curl/子进程访问同一端点正常，重启服务或 refresh_config 后立即恢复。第三轮复现（07:31:17 运行时报 refused ↔ 07:31:18 shell 8/8 成功）。

根因：provider client 在构造时固定连接/代理配置。远程 provider `trust_env=True` 时 httpx 经 urllib 读取 macOS 系统代理（Surge 等），代理拓扑在构造后变化 → 缓存实例持续拨号旧端点，自身永不自愈。

修复（commit 3bf8364be，gen20）：
1. LLMClient 新增 `on_transport_failure` 回调 + `_notify_transport_failure()`：传输级失败按次上报，hook 异常绝不影响调用结果。
2. ConnectError 的单次重试前加 0.5s 退避（毫秒级原地重试对拒连无效）。
3. ModelClientPool 为每个 provider/model 注入 hook → `retire_client_for(p, m)`：弹出缓存并登记退休（同 replace_registry 语义，最后引用释放后才关闭 transport），下次调用按当前配置重建。重试次数/降级/严格模式语义不变。

验证：
- 单测：pool 失败后重建 + 幂等退休；187 项 LLM/pool/provider/fallback 测试通过。
- 活体（真实拒连端口，非 mock）：Errno 61 → LLMNetworkError（0.51s）→ hook 2x → 下次 get_client 返回新实例 = PASS。
- 未证：事故当时的确切触发（代理端口变更）未复现；若代理真正宕机，本修复不能凭空恢复连通性（只消除本侧陈旧实例）。