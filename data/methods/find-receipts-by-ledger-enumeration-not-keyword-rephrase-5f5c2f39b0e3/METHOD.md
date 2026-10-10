---
method_id: find-receipts-by-ledger-enumeration-not-keyword-rephrase-5f5c2f39b0e3
name: find-receipts-by-ledger-enumeration-not-keyword-rephrase
description: 需核实先前启动的后台任务/历史工具动作的状态或结果而 job_id/句柄不在上下文时，其权威记录是动作/证据账本中按不透明 ID 键控的回执（如 job_output evidence）。回执正文是机械文本（任务号、命令、exit code、统计行），与语义猜测关键词无必然重叠。本集首次关键词搜索 miss 后又换词重搜一次，共 5 次调用（2 miss + list + 2 次 hydrate）才定位到回执；正确模式是首次 miss 即切换为按时间/来源类型枚举账本（list_evidence），命中 ref 后直接 hydrate 回执首段与尾段，约 2 次调用即得带时间戳结论，并立即回到主任务。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8edca76a-022e-442c-9819-960bcdff7f8a:1121:b41679d08d44c26f62dd
evidence_refs: learning:learn:43ed3e553b83
created_at: 2026-10-10T07:40:12.757937+08:00
updated_at: 2026-10-10T07:40:12.757937+08:00
---
## Trigger
需要核实先前启动的后台任务或历史工具运行的状态/结果，且其 job_id/句柄不在当前上下文；或对同一回执/证据存储的内容关键词搜索已出现一次 miss。

## Discriminator
目标工件是回执类记录：以不透明 ID 键控，正文为机械回执文本而非语义叙述。首条 miss 回执（『未找到匹配…的当前会话 Evidence』）在当时就证明关键词猜测与回执文本无重叠；同族工具 list_evidence 可按最近窗口枚举账本，可覆盖时间上邻近的回执，无需猜词。

## Short path
- 用一次轻量进程/状态检查回答『是否仍在跑』；若不在跑，未知量收敛为『已完成还是未启动』，停止间接信号推断
- 直接 list_evidence 最近窗口（或按 source 类型如 job_output 过滤），按时间在账本清单中定位回执 ref
- hydrate 回执首段：确认 job_id、命令、终态与 exit code
- 按 range 续读回执尾部取结果统计行，形成带时间戳的绿/红结论（如『06:53 于 tip X 上 7316 passed』）
- 回执确认后立即回到主任务（合并/重启），不做补充确认

## Stop conditions
- 回执已 hydrate 且显示终态（done/failed + exit code + 结果统计行），未知量已被权威来源回答
- 枚举一次加定向 hydrate 仍未找到时，改用任务系统原生按 ID/类型查询或显式询问用户，不做第三次关键词变体

## Verification
- 回执内容与上游一致：job_id、命令行指向目标仓库与目标测试集，acquired_at 时间戳支持所声称的完成时点
- 结论表述为带时间戳的快照（『06:53 于 1b5a060cd 上 7316 passed, exit=0』），不得写成无时间限定的『绿/仍在跑』

## Counterexamples
- 回执或日志文件名本身含稳定语义标签（如以任务名命名的日志），关键词一击即中——此时关键词搜索才是窄路径，枚举反而是绕远
- 进程表直接给出答案（pytest 活跃运行、CPU 持续增长）——『是否完成』已被回答，无需再找回执
- 账本规模巨大且 list 窗口覆盖不到久远记录、又无来源类型过滤——枚举会 miss，应改用按 tool_name/job_id 的结构化查询
