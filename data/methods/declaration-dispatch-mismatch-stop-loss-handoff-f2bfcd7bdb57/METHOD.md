---
method_id: declaration-dispatch-mismatch-stop-loss-handoff-f2bfcd7bdb57
name: declaration-dispatch-mismatch-stop-loss-handoff
description: 当连续多轮输出『即将执行』的声明或元调用（convergence/计划复述/自纠承诺），而工具回执中始终没有目标动作，且每次自纠仍是同通道的声明文本时，元层承诺零信息增益。方法：以回执为准检测目标动作缺失；miss 第 1 次就把输出压缩成纯动作调用；第 2~3 次 miss 即止损——汇总已验证事实，把下一步写成用户可直接复制的精确命令交接，不再产生任何声明轮。本集该止损点迟至第 12 轮才触发，烧掉约 10 轮、8 万 token 而未知量（鉴权机制）零缩小。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d4b773f7-7796-4ff1-a76a-310f94b7feff:803:be4577643ea11b98101c
evidence_refs: learning:learn:849aa3532b04
created_at: 2026-09-25T13:56:04.618275+00:00
updated_at: 2026-09-25T13:56:04.618275+00:00
---
## Trigger
计划好的外部动作（如 execute_command）在工具回执中连续缺席≥2轮，同时输出充满执行意图声明、边界承诺、自纠宣言或 convergence 类元调用

## Discriminator
回执本身即可判定：self-history/工具记录显示上一轮只新增声明类条目（placeholder、『同上』、guard 文案）且没有任何目标动作类型的回执，rounds/tokens 计数在涨而无新命令结果；且自纠尝试与故障同通道（都是文字声明）——据此在 miss#1/#2 即可断定『更多承诺』不会改变行为，无需等到第 11 轮

## Short path
- 每轮核对回执而非自己的意图：目标动作类型（execute_command 等）是否真的出现新回执
- miss#1：下一轮输出仅含该动作调用本身——零正文、零元调用、零承诺语句
- miss#2：确诊同通道自纠无效，停止一切 convergence/声明类输出，不再写任何『这次真的执行』
- 止损交接：一屏给出（a）已验证事实清单（b）当前唯一未知量（c）用户可复制直接执行的精确命令（无占位符）+ 需回贴的输出
- 若后续回执显示派发通道恢复，再接管继续执行

## Stop conditions
- 目标动作回执出现并返回结果 → 退出本模式，恢复正常流程
- 用户侧交接命令已给出并明确所需回贴内容 → 本轮立即终止
- 止损交接后不再追加任何新的声明/元调用轮（每次追加都是故障本身）

## Verification
- 统计最近 N 轮工具回执中目标动作类型出现次数是否由 0 变为 1
- 交接命令可直接复制执行、无占位符、恰好覆盖当前唯一未知量（本集为鉴权 token 键/header）
- 声明类文本总量不再随轮数增长；run_vitals rounds 增长伴随新动作回执而非纯声明

## Counterexamples
- 单次因格式/参数笔误漏发动作、下一轮重试即成功——不应升级为用户交接
- 工具已发出但返回错误/超时（401/500）——属于重试或换参数问题，不是声明-动作错位循环
- 用户明确要求必须由代理自主完成且无人工可交接的批处理场景
- 『声明』轮实际在产出用户正在消费并回应的内容——不是空转，不应触发止损
