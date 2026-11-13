---
method_id: resume-interrupted-pipeline-at-first-unverified-gate-8b7b0cae0c47
name: resume-interrupted-pipeline-at-first-unverified-gate
description: 极简「继续」到达且本会话无 task state、无活动 goal，而 evidence 列表最新条目在近数十分钟内密集聚簇、来源为具体命令/子代理回执（即上一轮在流水线中途被打断）时：续跑对象就是这簇证据指认的在途流水线，唯一恢复未知量是「最后一个通过的是哪一闸」。用该流水线自身的回执/产物文件定位第一个缺 PASS 回执的闸并从那里续跑；不重扫全量 goal 注册表、全仓目录或全工作区事件流，也不重推导整条管线。
aliases: 断点续跑先查最新回执, 接手中断的班从哪一步继续, 被打断的会话怎么恢复进度, 续跑别从头再来, 找第一个没验收的步骤接着干
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:945951a9-56ef-44ec-9803-1454213b85fc:191:b8c797419f72270caae0
evidence_refs: learning:learn:fb178e6f9fe0
created_at: 2026-11-13T10:04:40.435380+08:00
updated_at: 2026-11-13T10:04:40.435380+08:00
---
## Trigger
极简续跑指令（如「继续」）到达；本会话无 task state、无活动 goal；list_evidence 最新条目时间戳密集聚簇（与当前时刻的缺口即中断时长），且来源为具体 execute_command/subagent_result 回执，指认唯一在途流水线

## Discriminator
「无活动 goal」回执加上 list_evidence 最新簇的时间戳与来源标签，当时已足以把『继续什么』从 76 个 goal/全仓缩到一条流水线；此后真正待解的只剩『哪一闸缺 PASS 回执』，这由该流水线自己的 receipts/产物文件直接回答，不需要 goal 注册表全量、全工作区事件流或仓库根目录枚举

## Short path
- 廉价状态检查（task state、active goal）确认为空，排除目标注册表路线
- list_evidence 最新优先，读最新聚簇：识别在途流水线与其最后执行的动作/脚本名
- 只水化该簇最新命令回执（退出码与输出中命名的产物路径）；如需确认无他人接手，补一段会话级（非全工作区）事件流尾部
- 只列该流水线的回执/产物目录，按闸序找出第一个缺 PASS 回执的闸
- 复用既有脚本从该闸续跑；产物按流水线自身验收字段验证并写收口回执后停止

## Stop conditions
- 最终闸回执已存在且 PASS（如 CLOSEOUT_VERDICT=PASS）：无可续，直接汇报现状
- 最新证据簇早于当前排期窗口，或多条流水线同龄聚簇歧义：退回排期/STATUS/goal 注册表的发现路径

## Verification
- 所续闸之前的每一闸在盘上都有 PASS 回执；若母稿已冻结，续跑产物身份（如 sha256）与冻结基线一致
- 收口回执字段与该流水线既有合同一致且 fails 为空

## Counterexamples
- 周期任务唤醒且该期可能已完成：最新证据簇可能是上一期的，应先按触发日期做产物存在性幂等核对，而非沿最新簇续跑
- 指令点名目标（如「X 继续」）：走具名 provenance/git-delta 式恢复，不适用最新簇判别
- 中断运行未留下任何回执/检查点产物：回执捷径失效，需要有界事件流重放
