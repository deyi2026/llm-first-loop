---
method_id: pipe-masks-exit-code-trust-payload-error-signatures-d268c65d9396
name: pipe-masks-exit-code-trust-payload-error-signatures
description: 以截断管道结尾（cmd | tail/head）或经后台 job 执行的验证命令，其退出码只属于管道最后一段：关键命令失败时回执仍可能是 success/exit=0。消费此类回执要先扫正文错误签名与输出形态，再决定是否采信状态头；构造验证命令时要保证决定性命令的退出码可归因（去尾管道/pipefail/输出落盘再截取）。命中 command not found 等签名即判『未真正执行』，不得据此宣称验证通过。
aliases: exit 0 假成功, tail 管道吞了退出码, 成功回执正文里藏着报错, 后台任务显示成功其实没跑, 先看输出再看退出码
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80a9ad77-9a07-4f8b-9da4-49adb180bd96:1701:7160489e146942cb577e
evidence_refs: learning:learn:6e75af5e9aa3
created_at: 2026-11-04T16:56:35.156514+08:00
updated_at: 2026-11-04T16:56:35.156514+08:00
---
## Trigger
要在仓库内运行测试/构建等命令并以结果作为结论依据，且命令串以 | tail/head 等截断管道结尾，或走后台 job 执行；也适用于已收到 状态=success/exit=0 但正文首行是 shell 报错、或输出形态（行数/摘要行）与预期明显不符的回执。

## Discriminator
发起命令时即可见的事实：『关键命令 | tail』的退出码归属 tail 而非关键命令，因此未来回执的 exit=0 天然不能证明关键命令成功。回执层面则表现为状态头 exit=0 与正文错误签名（如 command not found）直接矛盾，且输出仅 1 行而预期是多行测试摘要。两者都不依赖事后才读到的答案。

## Short path
- 发起验证命令前自查命令串：决定性命令若不在管道最后一段，先去掉尾管道/加 pipefail/输出重定向落盘再截取，使未来回执的退出码可归因
- 消费回执时先读正文（首行错误签名＋末行摘要＋行数）再读状态头：出现 command not found/No such file/traceback 等签名即判失败，无论 exit 码
- 确认为解释器/环境缺失后，一次性解析项目权威解释器（如 ls 项目虚拟环境 bin）并以绝对路径重跑一次，不逐个试 python/python3
- 重跑回执同时满足 exit=0、正文含预期摘要行（如 N passed）、输出形态与真实运行匹配，才可宣称验证通过

## Stop conditions
- 回执 exit=0 且正文含与命令匹配的成功摘要、无错误签名、行数形态一致 → 采信结果并停止
- 已用权威解释器成功复跑一次 → 不再重复探测环境或重复执行同类验证

## Verification
- 对照实际执行的命令串，确认决定性命令是管道最后一段（或无管道）
- 重跑后的回执正文应包含可数的成功摘要行（如测试通过数），且总行数与一次真实运行一致

## Counterexamples
- 无管道的前台命令 exit=0 且无输出：退出码本身可信，无需逐行审正文
- stderr/stdout 只含良性提示（git hint、deprecation warning）：非错误签名，不得误判失败
- 确实必须截断超大输出时：应重定向到文件后 tail 文件或用 job 系统自带输出窗口，而不是在关键命令后直接接 | tail 后依赖退出码
