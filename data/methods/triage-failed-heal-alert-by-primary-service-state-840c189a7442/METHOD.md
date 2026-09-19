---
method_id: triage-failed-heal-alert-by-primary-service-state-840c189a7442
name: triage-failed-heal-alert-by-primary-service-state
description: 告警称自愈/重启等恢复动作失败时，先直接测主服务现状再定优先级：用进程启动时间+身份匹配、活跃连接或端点探测两条证据判定。告警文本若全是引导阶段错误（DNS/DoH 拨号失败），说明失败的是'要新起的实例'而非'在跑的实例'；若主服务健康且失败实例未接管，即将告警降级为有界副作用失败，触发方排查只做时间盒内的定向 supervisor 搜索（launchd/cron/按服务名过滤的脚本），不做全目录扫描或读取无关调度内容。若主服务不健康，优先级反转为先恢复服务。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:aebefe75-53be-4da9-a28b-55b5edf767f8:0:b1715cc82023efb1d7c9
evidence_refs: learning:learn:1c266af9a17a
created_at: 2026-09-17T22:59:49.115563+00:00
updated_at: 2026-09-17T22:59:49.115563+00:00
---
## Trigger
告警/报错描述的是恢复类动作（restart、self-heal、failover）失败，错误文本为引导阶段错误（DNS/DoH 解析、依赖拨号失败），而主服务本身是否宕机未知

## Discriminator
第一步 ps 即可见：主服务进程存在且启动时间早于告警窗口（按 config/token 路径匹配身份、区分同名兄弟实例）；且告警错误全部来自'正在启动的实例'而非在跑实例掉线。这两点在进入任何目录枚举之前就已足够把'服务宕机'与'侧动作失败'分开

## Short path
- 读告警：错误属引导阶段（DoH/DNS 拨号失败）→ 假设是新实例起不来；未知量=在跑主服务是否受损
- ps 匹配服务进程身份与启动时间，区分同名多实例（如 token 隧道 vs 命名隧道）
- lsof 查该 PID 到上游 edge 的 ESTABLISHED 连接（或探测公网端点）→ 主服务健康则告警降级为有界副作用失败
- 对齐时区后在服务自身日志核对告警时刻：无重启/接管痕迹 → 确认失败实例未造成损害
- 触发方排查仅做定向：launchd/cron/按服务名过滤的脚本，时间盒内完成；查不到即报告'触发方在外部+主服务已实测健康'并停止，不扩大到全目录/无关调度文件

## Stop conditions
- 主服务经连接/端点实测健康，且失败实例确认未接管、未写入服务日志 → 无需恢复动作，输出有界结论
- 进程缺失或启动时间≈告警时刻 → 失败的恢复动作即事故本身，切换为恢复优先（先修引导路径如 DNS 兜底）
- 定向 supervisor 面（launchd/cron/服务名过滤的脚本）查不到触发方 → 停止扩大扫描，声明触发方在外部

## Verification
- 按 config/token 路径匹配进程身份，而非仅按进程名（多实例并存时防张冠李戴）
- 日志时间戳换算到告警时区（UTC vs 本地）后再做时刻对齐
- 可用同 config+独立 metrics 端口临时拉起第二实例实测'现在重启是否会成功'，随后清理，作为恢复可行性证据

## Counterexamples
- 主服务进程不存在或启动时间就在告警时刻：失败的恢复动作就是宕机本身，应先修引导路径恢复服务，健康分诊反而拖延
- 告警错误来自在跑实例（established 连接被终止）：不能当作良性副作用失败
- 恢复器是先 kill 后 start 模式：即便当前健康，旧实例仍可能被杀，'爆炸半径有界'在排除 kill 行为前不成立
- 同名多服务且未做身份匹配：健康的那只可能是兄弟实例，健康结论与被告警的服务不符
