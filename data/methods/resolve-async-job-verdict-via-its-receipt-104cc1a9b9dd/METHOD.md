---
method_id: resolve-async-job-verdict-via-its-receipt-104cc1a9b9dd
name: resolve-async-job-verdict-via-its-receipt
description: 需要判定一个后台/异步任务（如全量测试 job）是否完成及结论时，不要用散文关键词检索、进程表 grep 或结果缓存（lastfailed 类）去重建结论——它们只命中残留：旧 run 的 fixture 进程、历史失败缓存，均不能证明当前 run 的结论。任务机制本身会落一张机读回执：job_id + 原始命令 + 声明的输出重定向路径，且已在 evidence/状态面可见。先定址回执（list_evidence→hydrate），按 job_id 查 status，再读声明的重定向文件（EXIT= 行、junit xml）取结论；回执终态但 0 行内联输出时，按回执自身提示以落盘文件交叉验证。本集该链路把约 5+ 次宽探查（keyword search miss→ps grep 噪声→缓存取证）压缩成 2 次定址读取，结论一次到位。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7c423f8-5e37-404b-a6b3-9631910a54d7:429:a82f6db8fc643359e2a5
evidence_refs: learning:learn:0f4a262c7e75
created_at: 2026-10-11T00:43:01.110513+08:00
updated_at: 2026-10-11T00:43:01.110513+08:00
---
## Trigger
任务中途需要回答『某个先前启动的后台/异步 job 是否完成、结论如何』，且该 job 由后台任务机制启动（存在 job_id 与输出重定向）

## Discriminator
回执可见且自含地址：evidence/状态面中的 execute_command/后台任务回执显式给出 job_id、完整命令与重定向输出路径（log/junit）。同一时刻 ps 输出里可见的只是旧 run 残留（Fri12AM 启动的 fixture 浏览器、pytest-43 临时目录），result 缓存只是历史 run 痕迹——两者对当前 run 结论均无证明力；唯有 job_id+声明输出文件是权威地址。

## Short path
- 先问结论归属：这个未知量的权威记录是谁写的→后台 job 的回执，而非 prose 库/进程表/缓存
- list_evidence（或后台任务状态面）定位该 job 的回执 ref
- hydrate 回执，取 job_id、原始命令、声明的输出重定向路径
- 按 job_id 查 status（done/exit）；读声明重定向文件（EXIT= 行、junit xml）得出结论数字
- 回执终态但 0 行内联输出→按其提示以落盘文件交叉验证后再下结论
- 结论到手即转回主任务（merge→update/publish→挂唤醒核验），不再对同一问题继续取证

## Stop conditions
- status=done 且重定向文件给出明确 exit/统计（如 EXIT=0 + 通过/失败计数）→ 停止取证
- status 显示仍在运行→不下结论，挂唤醒/等待，不重复轮询
- 找不到任何回执且确认 job 不经后台机制→本方法不适用，转进程/文件取证

## Verification
- 结论数字必须来自声明的输出文件（junit/log），不得仅凭 0 行内联输出的回执
- 校验 job_id 与回执一致、输出文件时间戳落在任务启动窗口内
- 结论表述为带时间戳的快照；存在并发写者时不宣称不可撤销终局

## Counterexamples
- 回执已丢失或任务不经后台机制启动：进程表+日志取证才是正路，本方法不应阻塞它
- 问题本身是 live state（『现在在跑什么/占多少 CPU』）：ps/top 是正确工具，回执只反映历史
- 目标是散文/知识型记录（文档、决定备忘）：keyword 检索才对；本方法只针对事件型 job 的结论
- 同步命令且回执内联已含完整输出与退出码：直接读回执即可，无需再定址重定向文件
