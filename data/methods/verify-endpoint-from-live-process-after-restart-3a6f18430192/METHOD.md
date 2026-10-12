---
method_id: verify-endpoint-from-live-process-after-restart-3a6f18430192
name: verify-endpoint-from-live-process-after-restart
description: 当目标本地服务刚被确认重启/重部署（状态输出已给出新 pid 与新 started_at）时，会话记忆中的 URL/端口一律视为未验证。先用进程事实（如按 pid 查监听套接字 lsof）解析出当前实际地址，再派发 navigate/connect；不要先按旧地址导航、失败后才回头诊断。本例可省去：一次注定失败的导航、一张浏览器错误页快照、一次 curl 探测和二次导航。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:1219:cc691bb02907cc64dd1b
evidence_refs: learning:learn:db605783a7b9
created_at: 2026-09-18T19:18:22.055372+00:00
updated_at: 2026-09-18T19:18:22.055372+00:00
---
## Trigger
上下文已确认目标服务发生 restart/redeploy（deployment/process 状态给出新 pid、新 started_at），而下一步基于地址的动作（navigate/connect）使用的地址来自重启前的记忆或旧输出，且当前权威状态输出中不包含该地址

## Discriminator
三个当时已知事实的合取：重启已确认；受管服务的新 pid 已知；待用地址产生于重启之前、在当前权威状态输出中无 provenance。这把“直接导航”从候选行动中提前排除，将下一步缩成“由 pid 解析当前监听地址”一个动作

## Short path
- 1. 从 deployment/process 状态确认 restart 终态并取得各服务 live pid（未知量：重启是否完成、目标进程是谁）
- 2. 用 pid 查监听套接字（lsof 按该 pid 过滤 LISTEN）得到当前地址（未知量：重启后服务实际在哪里监听）
- 3. 只做一次导航到已验证地址；快照确认到达应用级页面而非浏览器网络错误页（未知量：应用是否可达）
- 4. 若为登录页，查 auth 配置判断是否存在可用程序化凭据（未知量：能否进入面板本体）
- 5. 若仅有密码哈希、无可用凭据，停止发现，向用户报告已验证事实并请求其手动登录

## Stop conditions
- 地址已由 live 进程的监听事实验证，且导航后快照为应用级页面（登录页也算），而非浏览器错误页
- 本会话内地址已验证且其间无新的 restart 事件，不再重复解析
- 访问被认证阻断且确认无可用凭据 -> 转入请求用户操作，不再枚举凭据来源

## Verification
- 导航后快照出现目标应用的语义对象（标题/按钮等），而不是“无法访问此网站”类浏览器错误页
- 监听该端口的进程 pid 与 deployment 状态中的受管服务 pid 一致（pid 与地址同源验证）

## Counterexamples
- 端口由当前权威配置/manifest 静态声明且未随重启变更 -> 直接导航即可，先查 lsof 是多余步骤
- 目标是远程/外部 URL，本地无进程可查 -> 本方法不适用，应走 DNS/健康检查路径
- 地址在本会话刚刚验证过且期间无任何 restart -> 无需重复验证
