---
method_id: attribute-run-origin-via-session-record-not-action-logs-f9106ca09382
name: attribute-run-origin-via-session-record-not-action-logs
description: 归因审计某 run/动作的发起方与授权时，动作/事件日志按 session id 键控、只含 run 内部决策记录且无 origin/parent/channel 字段——触发来源与授权事实存放在 session 记录本身。首读日志拿到 session id 后应直接 join 到 session 文件（metadata+首条与全部用户消息），再用活体工件核验其自述终态；不要对同一日志类换参数重查或重读截断 hydration blob 期望长出来源字段。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:295:26ca881200311a81adff
evidence_refs: learning:learn:7b630e728317
created_at: 2026-10-14T15:18:07.976615+08:00
updated_at: 2026-10-14T15:18:07.976615+08:00
---
## Trigger
需要归因事件/审计日志中出现的 run 或动作（谁触发、从哪来、是否经用户授权），且日志条目按 session id 键控、只记录 run 内部 llm/tool 决策，首读即可看出条目中没有来源类字段

## Discriminator
首读日志已暴露的结构事实：全部条目形如 action_trace session=<id>: action.llm_decide tool_calls=…（载荷截断），整条流不含 run 创建者/parent/触发通道字段；而 join key（session id）已到手，session 记录（created_at/parent_id/channel/title/首条用户消息）才是该未知量的归属记录类

## Short path
- 读一次工作区级事件流：提取 session id、时间戳、动作与 reason，先解决『哪个 session 在何时发了什么』
- 对照日志 schema 判定剩余未知量的归属：日志无 origin/parent/channel 字段 => 触发方/来源/授权不在日志里，立即停止对日志类的追加查询（不再换 query、不再读截断 blob）
- 用已提取的 session id 直接打开对应 session 记录，读 metadata（created_at/parent_id/channel/model/title）+首条用户消息 => 回答『它是谁、从哪来』
- 提取该 session 全部用户消息 => 回答『用户授权了什么』，重建从原始请求到争议动作的授权弧线
- 对该 run 自述的终态改用活体权威工件核验：从工作区根路径读配置文件当前值、检查进程存活，不采信 run 的自我收口声明
- 触发方、授权链、终态三类事实各有归属记录背书后停止；若旧经验/报告的归因与新事实冲突，顺手修正记录并附证据引用

## Stop conditions
- 触发方（session metadata）、授权链（用户消息实录）、终态（活体工件实测）三类事实均取得直接证据
- session 记录缺失或已轮转时才降级到日志翻页/OS 级取证等更宽发现
- 日志类已被证明不含来源字段后，不再对其换参数重查、翻页或重读 hydration blob

## Verification
- session 记录的 created_at 与日志中该 session 首条事件时间吻合；parent_id/channel 支撑『用户会话 vs 子代理/调度』结论
- 活体配置文件当前值与该 run 声称的改动一致（含裁决注释落盘）；进程检查为空确认已终止
- 修正旧记录时引用 evidence ref，且新归因能完整解释原异常现象的时间线（如竞态窗口、屏障互斥）

## Counterexamples
- 日志条目本身携带 launched_by/parent_run/trigger 等来源字段时，直接由日志回答归因，无需解析 session 文件
- 未知量是『run 内部具体做了什么动作/参数』时，action log 就是正确记录类，先读日志而非 session JSON
- session 记录不存在（跨机分布式 trace、日志已归档脱机）时 join 不可用，回到日志翻页或 OS 级取证
