---
method_id: live-job-handle-before-index-and-telemetry-enumeration-afa65afe53fc
name: live-job-handle-before-index-and-telemetry-enumeration
description: 摩擦起点：goal 状态已显示唯一 open/ready 任务被一个进行中的后台批跑阻塞、且历史事故已定义，待解未知量仅为'当前 run 健康度'，此时先做了证据索引全量枚举（20/463）、两次 50-100 字符截断快照水合、会话事件流读取等低信息宽枚举，之后才直查 job 状态并进入 run 目录。11 次调用中约 4 次可省。方法：当存在活跃执行句柄（durable job、已注册轮询提醒、作业命令中的 run id+日志路径）时，直接沿句柄查作业状态与落盘工件，用预注册判据核对；仅当无活跃句柄或句柄失效时才扩大到索引/遥测枚举。本例 11 次调用中约 4 次（list_evidence、两次 50-100 字符截断水合、event_stream）为低信息枚举，最短路径约 5-6 步即可支撑同样的下一步建议。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:973:c4ab2a765536c2e93199
evidence_refs: learning:learn:93b8e4fd5b29
created_at: 2026-09-21T02:56:48.262159+00:00
updated_at: 2026-09-21T02:56:48.262159+00:00
---
## Trigger
用户请求下一步/判定建议；goal 或任务面板显示唯一 ready 任务被一个仍在运行的后台批跑（durable job）阻塞；系统中存在已注册的轮询提醒或作业句柄

## Discriminator
是否已存在指向该未知量的活跃执行句柄：durable job id、轮询提醒（sched-*）、或作业命令中显式的 run id 与日志/工件路径。goal 状态在枚举发生前就已表明唯一 open 任务是执行与预注册解读、并给出三次事故 checkpoint，即未知量只剩 run 健康度；该句柄的存在把'全部证据库/会话流'缩为'一个作业 + 一个 run 目录'。另注意 run 目录旁存在多个历史失败兄弟目录，必须用作业的 --confirm-run-identity 锁定唯一目录

## Short path
- 读 goal/task frontier：确认唯一 open/ready 任务与阻塞它的门 → 待解未知量=当前 run 健康度，不做其他枚举
- 解析活跃句柄：直查 durable job 状态（或已注册轮询提醒）获得 job id、run id、日志与工件路径；不枚举证据索引、不读会话遥测
- 仅读该 run 目录的权威工件：rows.jsonl 行状态、每行 worker.log 尾部、对预注册事故签名（如工具逃逸关键词）做逐行 grep 计数、产物完整性抽查
- run 未结束：报告实测进度（已完成/总行数、签名复现情况）+ 一次有界复查计划（沿用已有提醒），停止发现
- run 结束：按 run 目录内已生成的预注册门槛文件判定，不临时改标准；任一行死则先取证（stage 日志+该行 worker.log）再决定下一版

## Stop conditions
- 行存活数与各事故签名已直接从 run 工件实测（而非从索引快照或会话遥测推断）
- 作业终态确认，且工件时间戳与 job 状态一致
- 门判所需输入已齐备，不再做补充性枚举或'再确认几个'式查询

## Verification
- 逐行重算核查项：事故签名关键词出现次数、oplog/分页产物完整性、rows.jsonl 行状态计数
- 工件目录的 run id 与作业 --confirm-run-identity 完全一致，防止误读历史兄弟 run 目录（本例同目录下有约 10 个历史 run 目录）
- job 状态中的启动时间与 run 目录内最新 mtime/行完成节奏相符，排除读入缓存快照

## Counterexamples
- 无后台作业（工作在会话内完成）时不存在 live handle，证据索引与会话流枚举才是合理首选
- 问题目标是追溯历史事故根因且相关工件已被覆写时，会话事件流/遥测是主要证据源，不应只盯当前 run 目录
- 用户询问与该 run 无关的事项（如设计文档评审、统计预注册内容）时，不得隧道式扎进作业状态
- 作业状态工具可能返回缓存快照而真实状态已变时，需以工件 mtime 或二次直查交叉验证后再下结论
