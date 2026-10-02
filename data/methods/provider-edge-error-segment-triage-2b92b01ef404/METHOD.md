---
method_id: provider-edge-error-segment-triage-2b92b01ef404
name: provider-edge-error-segment-triage
description: 当对外 URL 的失败探针拿到的是 CDN/隧道提供方专属状态码（如 Cloudflare 530 = 无存活 connector），而非传输层失败时，该状态码本身就是分段 provenance：DNS、出站链路、provider 边缘均已被证明可达，故障只剩 provider→origin 一段。应直接诊断该段的 connector/agent 进程及其启动参数中的环境假设（如写死的 --edge-bind-address、config 文件），而不是先复核已被排除的本地段（hosts/DNS/端口/本地 curl）或做仓库级宽泛搜索。定位根因须落到一个可观察的状态错配（如本机 IP 已变而参数写死旧 IP），修复后以边缘连接数恢复 + 原 URL 端到端成功收尾。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f3313a03-3000-4d38-b4ba-bc7b6a82c817:0:7d50a6dc93454e4f12ce
evidence_refs: learning:learn:37d501951274
created_at: 2026-10-01T17:01:02.994822+08:00
updated_at: 2026-10-01T17:01:02.994822+08:00
---
## Trigger
用户报告公网域名/URL 打不开；对该 URL 的探针以退出码 0 返回非标准/提供方专属 HTTP 状态（如 520-530 段的 Cloudflare 530），而不是 timeout/refused/NXDOMAIN 等传输层失败；且已有独立信息表明本机 origin 服务存活。

## Discriminator
两条探针时已知事实：① curl 退出码 0 且拿到 HTTP 530 —— 530 由 Cloudflare 边缘发出，能拿到它就证明域名解析、出站代理、CDN 边缘全部已打通，只剩源站段不可达；② 状态输出已显示 web 服务存活（pid 63371、generation 稳定）。两者共同把故障域从『整条链路』缩到『Cloudflare→本机隧道 connector』唯一一段。

## Short path
- curl 失败 URL 并读取具体状态码；未知量：故障在哪一段链路。
- 返回 provider 专属 530 且 origin 已知存活 → 跳过本地 hosts/DNS/端口/本地 curl 复核，直查隧道 connector；未知量：connector 是否存活并已连上边缘。
- pgrep/launchctl 查 cloudflared 进程，并请求其 --metrics 端口的 /ready 或 ha_connections 指标；观察到进程在但 ha_connections=0、readyConnections=0。
- 读进程参数/plist，发现写死 --edge-bind-address 192.168.3.253；未知量：该 IP 是否仍属于本机。
- ifconfig 查当前网卡 IP=.170，与 .253 错配 → 根因：DHCP 换 IP 后 launchd 参数过期。
- 修 plist（去掉/更新写死 IP）→ reload launchd → 验证 ha_connections≥2 且原 URL 返回 200/303，停止。

## Stop conditions
- provider→origin 段确认 connector 已连接（ha_connections>0 / /ready 200）且原始 URL 端到端恢复成功，即停止诊断。
- 探针若是传输层失败（timeout/refused/NXDOMAIN），本方法不接管诊断，回退本地 DNS/网络排查路径。
- 返回码或响应体显示源站已被实际到达（如源站自身的 500/应用错误 JSON），放弃隧道假设改查应用。

## Verification
- 修复后同时验证段级指标（tunnel /ready 200、ha_connections≥2）与端到端原始 URL（200/303），两处都过才算闭环。
- 根因断言必须落到一个可观察的状态错配（当前网卡 IP vs 进程参数写死 IP），不允许『进程在跑所以没问题』式推断。

## Counterexamples
- curl 超时或 DNS 解析失败：没有 provider 状态码，任何链路段都未被排除，不应直接跳去查 connector。
- 域名并非走隧道/CDN（直接 A 记录到源站）：530 的『无 connector』语义不成立，需先确认域名路由方式。
- 拿到的是源站应用自身错误（500 + 应用错误体）：源站已被到达，问题在应用而非隧道，本方法不适用。
- provider 返回 401/403/WAF 挑战：边缘在主动拦截，connector 可能完全正常，处置路径不同。
