---
method_id: attribute-health-alarm-to-owning-instance-via-per-instance-telemetry-d3a0cd006bc4
name: attribute-health-alarm-to-owning-instance-via-per-instance-telemetry
description: 当监控 UI 报出某健康指标异常（如 HA 连接数=0/连接异常），同时存在独立可用性症状（502/Failed to fetch）时，不要默认该指标属于你已知的那套组件：主机可能并行运行多个同类基础设施实例，报警的那个未必承载真实流量。先从进程命令行/配置提取每个实例自己的 telemetry 地址（--metrics 端口）逐一查询，用数据路径实例自身指标验证报警真伪；再用源站 health 的 bootId/uptime 识别重启窗口解释瞬时 502；最后用流量计数器差分（N 次请求→恰一个实例 +N）做归因铁证。避免把『持续假警报』与『瞬时真故障』合并成一个错误假设去修健康组件。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1cab47b4-030c-4983-a640-0cfa5aa464d9:12:5c271beb4cf84c7cc81c
evidence_refs: learning:learn:199e6e0957f8
created_at: 2026-10-13T22:18:09.960302+08:00
updated_at: 2026-10-13T22:18:09.960302+08:00
---
## Trigger
监控面板/错误消息报出具体健康指标异常（连接数=0、异常、unhealthy），同时客户端有独立可用性症状（fetch 失败/公网 5xx），且主机上可能并行运行多个同类组件实例（两条隧道、两套 sidecar、新旧并存进程、多副本）。

## Discriminator
当时即可观察的事实：进程列表里每个实例的命令行通常自带自己的 telemetry 地址（--metrics 端口）；源站 health 响应常含 bootId/startedAt/uptimeSecs；各实例有独立请求计数器。先查数据路径实例自己的指标——若其实际正常（如 HA=2），则 UI 报警必然属于另一个实例；若源站 uptime 仅几十秒且 bootId 已变，则 502 落在重启窗口内，属瞬时故障而非隧道断连。这两个事实无需任何后续信息即可把『隧道故障/源站故障/客户端故障/假警报』四个假设缩到一两个。

## Short path
- curl 公网端点一次复现症状：拿到服务器返回的 5xx 即证明是服务端故障，不再分支到 CORS/客户端假设（服务器能回 502 说明网络与域名解析正常）
- 从进程命令行/配置提取每个运行实例自己的 metrics 端口并查询，判断数据路径实例的报警指标是否真的异常
- 若数据路径实例指标正常但公网 502，把假设收窄到本地源站：读源站 health 的 bootId/uptime，uptime 极短 => 502 处于重启窗口
- 再次 curl 公网验证已恢复；用 bootstrap/应用日志还原重启时间线，确认故障窗口闭合
- 定位报警真正归属的实例（另一个 metrics 端口显示 0、其日志呈周期性自愈循环），并做计数器归因测试：连发 N 次公网请求，确认恰有一个实例计数 +N
- 输出两个相互独立的结论并各自附证据：瞬时真故障（重启窗口，已自愈）与持续假警报（非承载流量的实例），只对真故障给修复建议

## Stop conditions
- 数据路径实例自身指标确实等于报警值（如服务隧道 HA 真为 0）=> 该实例真故障，直接按该实例排障，停止归因工作
- 公网端点持续 200 且计数器归因唯一 => 停止，带证据宣布持续报警为假警报，不修改健康组件
- 报警来源无任何可独立查询的 telemetry 或日志 => 只结论『数据路径验证为正常』，不强行归因

## Verification
- 流量计数器差分：连发已知数量 N 的公网请求，验证恰有一个实例的请求计数器精确 +N，其余实例不动
- 交叉核对报警实例自己的 metrics 端口与日志（周期性重建/持续 HA=0 循环），确认它与数据路径实例是两个不同进程
- 源站 bootId 变化时间与 502 观测时间窗对齐，且重启后公网恢复 200

## Counterexamples
- 主机上只有一个该类组件实例，且其 telemetry 证实报警（服务隧道 HA 真为 0）=> 真隧道故障，套用本方法只是浪费归因步骤，应直接修隧道
- 公网 curl 返回 200 而仅客户端失败 => 这是 CORS/代理/DNS 等客户端侧问题，不存在实例归因问题
- 报警指标无 per-instance telemetry 可查（UI 完全黑盒）=> 无法归因，只能报告端到端验证结论并建议加观测
- 源站 health 不暴露 bootId/uptime 等版本信息 => 重启窗口判别法失效，需改查进程启动时间或系统日志
