---
title: "公网 MCP \"tool failed internally\" 三步判别：链路/服务/凭证分离定位"
scenario: MCP Console 公网工具调用失败（The tool failed internally），需区分：隧道断/服务挂/客户端token过期。同名 hostname 被两条 cloudflare tunnel 声明时尤其易误判。
root_cause: ""
solution: 三步判别法：①无token curl 公网 /mcp 看 401 vs 530（401=链路通、鉴权挂）；②日志时间对齐找服务端拒绝记录；③从 console.db channels.mcp_access_token 取当前 token，本地+公网各 curl 一次 tools/list，都 200 ⇒ 客户端持旧 token，去客户端更新即可，隧道与服务无需动。
evidence: "本会话 execute_command 回执：①无token POST https://mcp.llmfirstloop.com/mcp → 401；②sidecar-console.log 18:36:23/.85/32.9/41.7 四条 \"MCP 鉴权失败\" 与用户三次调用时间对齐；③sqlite3 console.db channels 表存在 4dbbf4ec|LFLM|enabled=1|token 32位；④用该 token curl 本地 127.0.0.1:8790/mcp 与公网 /mcp tools/list 均 HTTP 200，90 个工具含 server_info/check_exec_environment；⑤ps 显示独立 cloudflared(pid 4183, tunnel a1cd626b, ingress 含 mcp.llmfirstloop.com→8790) 自周四持续运行，内置连接器 18:00 后未运行而公网仍 200。"
tags: [mcp-console, cloudflare-tunnel, auth-401, troubleshooting, lflm]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T18:43:14.120894+08:00"
updated_at: "2026-10-13T18:43:14.120894+08:00"
---

背景：MCP Console 场景，公网域名 mcp.llmfirstloop.com 同时被两条 Cloudflare Tunnel 声明（内置 Rust 连接器 named tunnel + 独立 cloudflared config.local.yaml）。客户端（LFLM）工具调用报 "The tool failed internally"，先后被误判为"隧道关闭导致断连"。

诊断步骤（本轮验证有效）：
1. 先用无凭证 curl 打公网 /mcp：返回 401 ⇒ 请求已穿透 cloudflared 到达后端，链路活着（若隧道真断会是 530/超时）。401/403 是"链路通、鉴权挂"，不要先动隧道。
2. 服务端日志 grep 调用时间点：`MCP 鉴权失败` 条目与客户端失败时间对齐（本例 18:36:23/32/41）⇒ 不是网络问题。
3. 通道 token 持久化在 console.db `channels.mcp_access_token`（sqlite3 可直接读）。取该 token 分别 curl 本地 127.0.0.1:8790/mcp 和公网 /mcp 的 tools/list：
   - 都 200 ⇒ 服务端+链路+token 全正常，故障在客户端持有的旧 token（token 有 updated_at，轮换后客户端未同步）。
   - 本地 200 公网 401 ⇒ 公网入口被劫持或指向别的后端。
4. 修复 = 客户端更新为当前 token，不动隧道与服务。

附带教训：
- 同名 hostname 双隧道时，公网 health 200 只能证明"至少一条通"。内置隧道 HA=0 自愈循环与真实服务无关，tunnelAuto=false 关停不影响服务——依据是"内置进程未运行时公网仍 200"。
- sidecar 日志中"Tunnel 跨 VPN 自愈守护已启用 + Tunnel: 未运行"这批行在【完整重启】和【配置重载】两种场景都出现，不能据此断言热加载；是否重启以 desktop-bootstrap.log 的 [desktop:start] 为准（本例 17:10/18:00/18:35 三次完整重启）。