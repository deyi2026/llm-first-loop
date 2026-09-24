---
method_id: edge-error-first-tunnel-split-brain-diagnosis-944a40a37ffb
name: edge-error-first-tunnel-split-brain-diagnosis
description: 公网域名入口不通时，最先取一次带错误码的公网探测：若边缘返回结构化隧道错误（如 Cloudflare 1033/530），故障已被定位到 edge-tunnel-origin 链路，应立即停止仓库/会话证据层的宽搜索（全仓 grep 只会命中 vendor 噪音）。随后逐层核对：本地 origin 是否存活、tunnel daemon 自报连接数、控制面 API 视角连接数。当 daemon 自报健康而控制面显示 0 连接（split-brain）时，信任控制面，对本地 tunnel 进程做干净重启，并以『公网错误码消失 + 控制面出现活跃连接』为修复判据。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5693816b-bf5b-467a-8a25-a8f48a50e29b:0:8fa5cb6eb476f133289e
evidence_refs: learning:learn:a9bdd2a78b8c
created_at: 2026-09-22T16:03:59.889541+00:00
updated_at: 2026-09-22T16:03:59.889541+00:00
---
## Trigger
用户报告域名/公网入口打不开或登录不了，且当前已有权威本地状态回执显示服务进程存活（pid_alive=true、restart_required=false 等），即本地 origin 大概率无罪，失败未知量在『域名→源站』网络链路而非代码内容。

## Discriminator
一次公网 curl 返回的边缘结构化错误码：1033/530 表示该 hostname 的 DNS 与代理配置正常、边缘明确认为 tunnel 不可达——把候选空间从『应用/代码/DNS/鉴权/隧道』直接缩到隧道层一个未知量。再叠加本地 daemon metrics（readyConnections=4）与 cloudflared tunnel info（0 连接）两个权威视图的矛盾，进一步把动作唯一化为『重启本地 tunnel agent』。

## Short path
- 读已有部署/服务状态回执：pid_alive=true、restart_required=false → origin 进程无罪，未知量=域名→源站链路（不需要全仓内容 grep）
- curl 本地 origin 登录入口：返回 303/200 → 源站应用无罪
- curl 公网域名取错误码：1033 → 边缘明确 tunnel unreachable，锁定隧道层，跳过仓库搜索与 DNS 排查
- 对同一 tunnel 取双权威视图：本地 daemon metrics 的 readyConnections 与控制面 cloudflared tunnel info 的连接数
- 两视图矛盾（本地 4 / API 0）→ 信任控制面，kill 旧 daemon 并按既有启动脚本干净重启 tunnel
- 复测：公网 curl 不再 1033 且 tunnel info 出现活跃连接后停止

## Stop conditions
- 公网探测返回正常状态码且能到达登录页（故障在会话/鉴权层，换假设，不动隧道）
- 控制面显示活跃连接且本地 origin 正常（故障在 ingress 路由/DNS/防火墙，重启 daemon 无益）
- 重启后公网错误码消失且控制面该 tunnel 连接数 >0，双视图一致

## Verification
- 公网 curl 错误码从 1033/530 变为正常业务响应
- cloudflared tunnel list/info 显示该 tunnel 至少 1 条活跃连接
- 本地 metrics readyConnections 与控制面连接数一致（split-brain 消除）

## Counterexamples
- 公网已返回 200、登录页渲染正常：是登录态/鉴权问题，套用本方法重启隧道无益
- tunnel info 显示活跃连接且本地 origin 可达：错误在 ingress 路由/DNS/防火墙，重启 daemon 无效
- 部署不含隧道（DNS 直连源站）：整条链不适用，应直接查源站可达性与防火墙
- 本地 origin curl 本身即失败：先修应用进程，不要进入隧道层排查
