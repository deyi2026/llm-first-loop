---
method_id: self-describing-403-plus-liveness-triage-50963831cd87
name: self-describing-403-plus-liveness-triage
description: 用户报『域名/服务连不上』类模糊症状时的分诊法：先做一次带传输细节的探测（DNS/TLS 是否完成），再打一个 liveness/身份端点（如 /health）。若非 2xx 的 body 自述原因（如 'remote web console disabled'、'requires auth'）且跨 UA 稳定，同时 liveness 200 带实例身份，则判定『可达但按策略拒绝』，按访问方式分诊并反问用户客户端与具体报错后停止发现；不要为此再做全库搜『开关出处』，也不要对稳定 403 继续 UA 轮换。仅当 liveness 也失败或 body 是无因的通用拒绝页时，才扩大到 tunnel/日志/历史经验检索。公网与本地身份字段（bootId）一致可证明同一实例。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1cab47b4-030c-4983-a640-0cfa5aa464d9:0:ba31b20ae9f4171e71b2
evidence_refs: learning:learn:37ba2d2d197c
created_at: 2026-10-13T22:14:42.429992+08:00
updated_at: 2026-10-13T22:14:42.429992+08:00
---
## Trigger
用户报告某域名/端点『连不上、挂了』等模糊连通性症状，且目标服务疑似存在 liveness 或身份端点（/health 等）可直接探测

## Discriminator
一次 verbose 传输探测即可得到两条判别事实：TLS/DNS 是否完成（可达性），以及非 2xx body 是否自述原因（策略拒绝 vs 故障）。跨 UA 稳定的自述性 403（如 'remote web console disabled'）+ liveness 端点 200 且带实例身份（bootId/version/uptime）⇒ 服务在线且拒绝是有意的，原因已由服务方自己声明，无需再找其他出处。

## Short path
- curl -sv 打用户报障的路径：未知量=传输层是否完成、4xx body 写了什么；跨 UA 稳定的自述性 403 同时排除 bot 拦截假设
- 同主机打 liveness/身份端点（/health 等）：未知量=实例是否活着、身份字段是什么
- 若 body 自述原因且 liveness 200：结论=『可达但按策略拒绝』，按访问方式（浏览器 UI / MCP 客户端 / 网络路径）分诊并反问用户具体报错，停止进一步发现
- 如需证明公网入口打到同一实例：比较公网与本地 liveness 返回的身份字段（bootId），一致即停
- 仅当 liveness 也失败或 body 为无因通用拒绝页时，才扩大到 tunnel/日志/历史经验全库搜索

## Stop conditions
- 已取得『传输可达 + liveness 200 + 拒绝原因由响应 body 自述』三要素，即输出分诊结论并向用户反问访问方式与具体报错
- 公网与本地实例身份字段一致后，不再为已成立结论做补充性全库/全日志搜索

## Verification
- liveness 端点返回 200 且携带实例身份（bootId/版本/uptime），而非仅 200 状态码
- 公网与本地（或备用路径）返回的身份字段一致，证明公网入口到达同一实例
- 403 body 在不同 UA 下稳定且为非通用的自述文案

## Counterexamples
- 403 body 是 CDN/WAF 通用拒绝页、无自述原因：自述判别不成立，需查 WAF 规则、tunnel 日志或历史经验
- liveness 端点本身也被同一策略禁用（如 /healthz 同样 403）：不能以它判活，需换身份端点或本地进程证据
- 所有端点均正常但特定客户端仍连不上（握手/协议/凭据层问题）：路径探测不解决，需客户端侧抓包与认证排查
- 纯本地服务无公网入口：直接查进程与端口即可，无需公网分诊流程
