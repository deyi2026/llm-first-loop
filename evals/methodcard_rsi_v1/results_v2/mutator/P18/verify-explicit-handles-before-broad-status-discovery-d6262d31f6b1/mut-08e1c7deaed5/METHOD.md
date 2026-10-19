---
method_id: verify-explicit-handles-before-broad-status-discovery-d6262d31f6b1
name: verify-explicit-handles-before-broad-status-discovery
description: 当状态回执已给出可直接核验的句柄（pid、id、endpoint、generation、时间戳）时，先用最小权威通道逐个核对句柄（如对回执中的 pid 直接 ps -p），而不是扩大到事件流回放、全进程宽 grep 等宽发现。句柄全部核验通过且剩余矛盾属用户指代歧义时，停止核验、汇总已证事实并定向追问；句柄核验失败才转入根因路径。本例中回执已给出 web=60104/feishu=60287 及 started_at，直接点查即可确认，可省去 workspace 级事件流查询和 ps aux 宽 grep 两次噪声调用。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b8938fdb-4321-481e-a154-cf8b4a6abc8c:13:388637e5a4fd0a378bcf
evidence_refs: learning:learn:7984f3840c57
created_at: 2026-09-23T01:02:10.754227+00:00
updated_at: 2026-09-23T01:02:10.754227+00:00
---
## Trigger
收到一份声称系统健康/重启成功的状态回执，其中包含可直接核验的具体句柄（pid、时间戳、版本号等），但目标事实尚未在权威层（OS/API）确认；或用户报告与回执表面矛盾

## Discriminator
回执中的显式句柄与时间戳在摩擦点之前已存在：process_versions 明确列出 web pid=60104 started_at=…23:36:31、feishu pid=60287 started_at=…23:36:44、code_current=true、exception_log 空。这把'进程是否真实存活'从'查所有事件/所有进程'缩小为对两个 pid 的点查，knowledge-at-time 成立

## Short path
- 用户称'重启不成功'；未知量：框架侧记录的重启/服务状态是什么 → 调框架状态回执（barriers、process_versions、exception_log），提取显式句柄
- 未知量：OS 进程表是否证实回执 → 直接对回执中的 pid 做 ps -p 60104,60287 点查
- 核对 pid 存活且 lstart 与 started_at 一致 → 框架可核事实穷尽：重启在框架侧成立；lfrt observation_failed 标注为唯一未证实面
- 剩余差异是用户指代不明（重启什么、在哪看到的）→ 停止核验，汇总已证事实表并向用户定向追问对象与症状

## Stop conditions
- 显式句柄全部在权威层核验通过（pid 存活、时间/版本一致），剩余不一致属用户指代歧义 → 报告事实+定向追问，不再扩大核验范围
- 句柄核验失败（pid 不存在/启动时间不符）→ 转入该服务专属根因路径（异常日志、该服务重启记录），而不是回退到全局枚举
- 回执未提供任何可核句柄（只有聚合健康标志）→ 此时才允许宽发现（全局 ps、事件流、目录）

- Verification 未逐条通过前不结案（覆盖全部 2 条验证条目）

## Verification
- ps -p <回执 pids> 输出包含这些 pid 且 lstart 与回执 started_at 一致
- 最终结论区分'框架可证事实'与'未证实面'（如 lfrt 观测失败不混同为重启失败）与'待用户澄清的指代'三层
- 调用数上限参照：本路径 3~4 次工具调用即可收敛，出现事件流回放或宽 grep 即视为偏离

## Counterexamples
- 回执只给聚合健康标志、没有 pid/时间戳等句柄时，OS 级确认只能靠宽发现（ps 全局/事件流），本方法不禁止也不应套用点查路径
- 回执显示某服务缺 pid 或已崩溃时，无句柄可跟，目标是失败根因，需要异常日志与事件历史等宽检索
- 用户已指明具体对象（如'WebUI 面板显示 feishu 重启失败'）时，窄路径是查该面板数据源/该服务的重启记录，而不是核全部服务 pid 后再反问对象
