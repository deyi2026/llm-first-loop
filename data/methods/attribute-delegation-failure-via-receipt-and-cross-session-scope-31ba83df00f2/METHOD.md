---
method_id: attribute-delegation-failure-via-receipt-and-cross-session-scope-31ba83df00f2
name: attribute-delegation-failure-via-receipt-and-cross-session-scope
description: 子代理工具调用返回 unauthorized 类失败、准备改配置重派时，不要把『我上次漏声明该工具』的记忆假设当成已确认事实——schema 只能解释机制（声明即截断），不能证明当时实际声明了什么。先水化 spawn/委派回执核对实际 tool_scope：失败工具若已在白名单内，配置层假设即刻证伪；再查 workspace 级异常日志，同类失败若跨会话或早于本次委派，即为平台层故障，重派必然复现，应改替代执行通道或等待修复。另：审计类数据直接从当前 git 真值重推，不做旧快照考古。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:33d3039e-2906-4f07-9dc7-517532290686:57:617274d3df7789e8688f
evidence_refs: learning:learn:be5d6648985c
created_at: 2026-10-14T17:38:01.832856+08:00
updated_at: 2026-10-14T17:38:01.832856+08:00
---
## Trigger
子代理/委托执行的工具调用返回 unauthorized/权限类失败，且下一步打算修改授权配置后重派重试时；尤其当归因依据是『我记忆中上次声明了什么』而非已核对的记录时。

## Discriminator
两条当时已存在的权威事实：① spawn 回执（spawn 时即落入 evidence）记录了子代实际生效的 tool_scope 白名单，失败工具在内/不在内一步可查；② workspace 级事件流/异常日志的时间戳与会话归属能显示同类失败是否出现在其他会话、是否早于本次委派——跨会话=平台层，仅限本次=配置层。

## Short path
- 拿到失败回执后，先不采信记忆中的『漏授权』假设；从 evidence 列表定位 spawn 回执并水化，对照实际 tool_scope 与失败工具名
- 失败工具不在白名单→配置层成立，修正 requires 后重派一次即可
- 失败工具已在白名单→查 workspace 范围事件流中同类异常的时间戳与会话归属：跨会话或早于本次 spawn→平台层，停止重派同配置子代理
- 平台层故障时改用替代执行通道（独立进程/直连工具）或等待修复生效；所需事实数据从当前 git/活真值直接重推，不依赖旧分析快照
- 向用户报告归因时区分『已证实』与『假设』，未核对回执前不使用『确认了』措辞

## Stop conditions
- 实际声明的白名单内容已从回执核实，失败工具在内/不在内已确定
- 失败作用域（仅本次委派 vs 跨会话/早于委派）已从异常日志确定
- 据此已判定重派是否可能成功；平台层未排除前不重派同配置子代理

## Verification
- 重派前：回执中 tool_scope 逐项对照子代理将调用的工具清单
- 归因『平台层』时：至少一条跨会话或早于 spawn 时间戳的同类异常记录；归因『配置层』时：回执白名单确实缺失该工具
- 改用替代通道后：确认原失败操作在新通道能成功执行，且子任务产出完整

## Counterexamples
- 回执白名单确实不含失败工具→配置层成立，直接修正后重派，无需跨会话排查
- 失败是业务性错误（合并冲突、测试红）而非权限类→本方法不适用
- 子代理状态是 cancelled（父回合结束连带取消）而非 unauthorized→归因点是父级生命周期管理（结束回合前先等待结果），与授权无关
- 环境仅单会话且无历史异常可查→跨会话判据不可用，只能靠回执核对加一次最小重试区分层级
