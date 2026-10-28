---
method_id: wire-truth-before-proxy-exclusion-tuning-c467334b7e2c
name: wire-truth-before-proxy-exclusion-tuning
description: 同机运行 TUN/透明代理类组件（Surge/Clash/VPN 等）时，应用连通性故障（如 P2P 打洞成功后 30 秒断开）先用 lsof 读该应用真实 socket 的本地源地址，再迭代排除规则：源地址落在保留测试段（198.18.0.0/15 等 fake-IP 池）即为本机拦截层接管流量的直接证据，应转向按应用/进程整体旁路，而非继续加宽排除 CIDR。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:87a1296f-1ec4-4fb1-9307-a09a02309ac3:112:5195d2b6d88e4eec6aec
evidence_refs: learning:learn:1d423b6d3e5a
created_at: 2026-10-16T19:34:20.929759+08:00
updated_at: 2026-10-16T19:34:20.929759+08:00
---
## Trigger
应用（尤其 P2P/UDP/长连接远程类）连通性排障，且同机进程清单已可见 TUN/fake-IP 代理、VPN 等透明拦截组件；或已陷入『逐条加排除 IP、/32 扩成大段』式规则迭代而症状仍复现

## Discriminator
故障期间一次按 PID 过滤的 lsof 即可取得：应用已建立外部连接的本地源地址若落在保留/测试段（198.18.0.0/15 fake-IP、100.64/10 CGNAT、169.254/16），则流量被本机拦截层接管；拦截组件的存在在最初进程/系统扩展清单里就已可见，该判别满足 knowledge-at-time，无需任何后续信息

## Short path
- 复现故障时列出该应用全部 socket（含 UDP），读本地源地址——未知量：流量实际从哪一层出去
- 源地址为真实网卡 IP -> 排除本机拦截假设，转常规路由/NAT/对端排查
- 源地址落在保留段（fake-IP 池）-> 判定被 TUN 接管，立即停止扩排除网段；未知量转为『如何让该应用整体绕过拦截层』
- 实施按应用/进程旁路（或临时停 TUN 做一次证伪实验），再复查 socket：源地址变为真实 IP、UDP 流出现在物理接口
- 连接存活时间超过原故障窗口即停

## Stop conditions
- 应用外部 socket 源地址已为真实网卡地址且连接稳定超过原故障窗口
- 本机不存在透明拦截组件且路由路径已由 traceroute/抓包证实
- 症状确认在对端或入站方向，本机出站 socket 已无诊断价值

## Verification
- 变更前后 lsof 五元组对照（保留段源地址 -> 真实源地址）
- P2P/长连接存活时间超过原故障阈值（如 >30s）
- 确认拦截组件仍在运行，排除『代理恰好挂了』造成的假阳性

## Counterexamples
- 主机无任何透明拦截组件：保留段源地址不会出现，此判别不适用，走常规网络排查
- 拦截发生在路由器/网关侧而非本机：本机 socket 显示真实 IP 但流量仍被劫持，需在出口抓包定位
- 故障为入站不可达（服务端视角）：出站 socket 检查无信息量，不应据此下结论
