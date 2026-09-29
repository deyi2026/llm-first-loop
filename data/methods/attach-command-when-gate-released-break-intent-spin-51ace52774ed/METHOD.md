---
method_id: attach-command-when-gate-released-break-intent-spin-51ace52774ed
name: attach-command-when-gate-released-break-intent-spin
description: 门控/回合预算循环中，若工具回执只返回 run_vitals/self_history 等治理遥测而非任务结果，且回执显示 boundary_released=true、顶部待办项连续多轮逐字不变、无新事实进入，则阻塞源是自身消息未附实际命令的意图空转。处置：下一条消息内联能解析顶部待办的具体命令（复用曾成功的直发模式）；若仍只换回遥测回执，立即 conclude 止损：诚实状态小结+单段可粘贴的用户侧命令块+各输出分支判定规则，不再换措辞重述意图。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d4b773f7-7796-4ff1-a76a-310f94b7feff:882:554d47ea1d60fbbc6c41
evidence_refs: learning:learn:3c12b5dc0693
created_at: 2026-09-25T14:05:32.080941+00:00
updated_at: 2026-09-25T14:05:32.080941+00:00
---
## Trigger
Agent 处于带边界门/回合预算的执行循环；工具回执返回治理遥测（vitals/history mirror/convergence 裁决）而非任务结果；回执含 boundary_released=true；self_history 顶部待办项与上一轮相同且本轮零新事实；此前存在『消息内联真实命令即被执行并返回结果』的成功先例回合

## Discriminator
同时可观察的两个回执字段：boundary_released=true（门已放行，不需要再声明）+ 顶部待办项逐字重复且无任何新工具事实进入，二者并存说明瓶颈是『我的上一条消息没有携带命令』而非环境阻塞。参照先例：第 1 轮直发命令的消息立即获得真实任务结果，而其后所有纯意图句都只换回遥测。

## Short path
- 门放行后的第一条消息：不写『现在执行 X』的意图句，直接在同一条消息内联能解析顶部待办的命令组（如读锁文件+列配置目录+grep token），一次解决两个未知量
- 若该消息仍只换回遥测回执：判定为通道性空转，立即进入止损，不做第二次同措辞尝试
- 止损=conclude：诚实状态小结（已确立事实逐条编号）+ 一段可整体粘贴的用户侧命令块 + 每个可能输出分支的判定规则（如锁含 PID→查死活→活则等待/死则重启服务自清锁）
- 停止：用户侧一步即可收口，不再消耗任何轮次

## Stop conditions
- 内联命令被实际执行并返回任务性输出（新事实进入 mirror）
- 连续 2 轮 released 回执且零新事实：强制 conclude 交回，不尝试第三轮
- 用户所需判定（如锁持有者死活、token 位置）已可由自身或用户侧单条命令解决

## Verification
- 每条门控消息自检：本消息是否包含可执行命令文本？若否且回执为遥测，记一次空转
- 对比相邻两轮 mirror 顶部待办项：逐字相同且无新工具输出即为空转信号
- 收口消息自检：用户只粘贴一段命令即可继续，且每个输出分支都有明确判定规则

## Counterexamples
- 回执显示 boundary_released=false 或 queue_pressure 存在等待项：此时等待或简短声明才是正确动作，不应强行内联命令或提前 conclude
- 待办项逐轮变化且新事实持续进入：这是正常收敛，不是空转，本方法不适用
- 遥测重复源于环境仍在排队/重试同一调用：等待即可，内联重发命令可能造成重复副作用
