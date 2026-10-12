---
method_id: tunnel-502-probe-local-origin-leg-first-af982e477878
name: tunnel-502-probe-local-origin-leg-first
description: 经本机反向隧道/代理（cloudflared、frp 等）把公网站点指向本地源站时出现 502/504：先从 ps 参数中可见的 config 路径，把失败 hostname 映射到本地 origin 地址（127.0.0.1:某端口），单次探测该端口并 tail 代理运行日志——一行 'connection refused to origin' 即可因果性锁定失败链路，然后再决定重启源站还是上探边缘/DNS。多代理实例并存时，必须先经各自实际加载的配置确认哪个实例服务该 hostname，再读它的 metrics，否则未归属实例的计数（如 total_requests=0）会制造假线索。链路排查按『最本地、最便宜的一腿先测、代理日志优先于平台侧枚举』排序。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a962d90b-199e-4a0c-af2f-3ce28b719bfb:280:5e1ad8f156e528774074
evidence_refs: learning:learn:455c10c53cff
created_at: 2026-09-23T06:49:14.401563+00:00
updated_at: 2026-09-23T06:49:14.401563+00:00
---
## Trigger
用户报告经本机反向隧道/代理暴露的公网域名返回 502/504 类网关错误，且本机可观察到代理进程与其启动参数

## Discriminator
第一步的 ps 输出已显示：连接器进程存活（带运行时长），且其命令行暴露实际加载的 config 路径——hostname→本地 origin 映射一步读取即得。对『连接器活着』的隧道 502，下一个最便宜可判定的未知量就是代理→本地 origin 这一腿（一次 curl + 一次日志 tail）。另外：多实例并存时 metrics 属于特定实例，确认归属前其计数不可作为路由结论依据

## Short path
- 复现公网错误 + 列出代理进程及完整参数：确认症状、确认连接器存活、从 ps 参数拿到正在加载的 config 路径（未知量：哪些链路环节有活组件、配置在哪）
- 读取该运行中代理实际加载的 config，把失败 hostname 映射到本地 origin 地址，并用 lsof 定位其运行日志 fd（未知量：流量在本机终止于哪里）
- 单次探测本地 origin 端口 + tail 代理日志：若出现 'Unable to reach the origin service / connection refused'，失败链路被因果性锁定（未知量：哪一腿失败）
- 仅当本地腿健康才外扩：按加载配置确认该 hostname 由哪个实例服务，再查边缘连接/DNS/隧道路由（未知量：平台侧）
- 定位死亡源站组件（lock/bootstrap 日志确认启动方式）并重启，本地探测与公网端点均返回预期码后停止

## Stop conditions
- 公网端点返回预期状态码（如未认证 401 / 200）且本地 origin 探测健康
- 代理日志已给出指向具体 origin 地址的失败原因行，且修复后不再新增同类错误

## Verification
- 重启后本地 curl origin 与公网路径各自返回预期状态码
- 核对代理日志错误时间戳与用户报错时间一致，确认因果链成立

## Counterexamples
- origin 存活且监听但自身内部返回 502：本地可达性探测通过，应查 origin 应用日志而非链路排查
- 代理/连接器进程根本不存在：应先排查连接器本身，本地 origin 探测不具优先性
- origin 绑定地址非本机回环或有防火墙：本地拒连不等于进程死亡，需区分 refused 与 filtered 并核对监听地址
- 失败 hostname 由另一台机器上的隧道实例服务：本机探测无意义，需先做跨机实例归属判定
