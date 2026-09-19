---
method_id: gate-rerun-exitcode-logfile-discipline-4718d9fcc0ad
name: gate-rerun-exitcode-logfile-discipline
description: 独立重跑他人申报的门禁（pytest/ruff/pyright/vitest/build）时，工具回显会被行数截断，导致为‘看到摘要行’而把整套测试全量重跑多遍。正确做法：把每条门禁命令包成 `cmd > /tmp/<gate>.log 2>&1; echo rc=$?`，以显式捕获的退出码为通过/失败权威信号，再从日志只 grep/tail 摘要行；远端 CI 用非阻塞轮询（gh pr checks / gh run view），不在有限时工具里跑 `--watch` 阻塞等待。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:1759:6e4425c33c4b7f5e4787
evidence_refs: learning:learn:7657bd6e11c5
created_at: 2026-09-19T08:15:24.930679+00:00
updated_at: 2026-09-19T08:15:24.930679+00:00
---
## Trigger
在输出有行数截断、执行有超时上限的受限 shell 工具里，重跑长输出的验证门禁或等待远端 CI 结果，需要独立核实另一方的通过申报。

## Discriminator
第一次运行结果中已同时出现两个事实：退出码 0（pytest 语义即全部通过）与‘[输出 N 行]’截断标记。这已足以判定门禁通过，缺的只是摘要行——应改变输出捕获方式，而不是重跑同一命令。

## Short path
- 重跑每条门禁前先包装为 `cmd > /tmp/<gate>.log 2>&1; echo rc=$?`，rc 即权威通过/失败信号，一次性解决截断问题
- 从日志只提取摘要：`grep -E 'passed|failed|error' /tmp/<gate>.log | tail -3`，不回显全量输出
- 若 rc 与摘要矛盾（如管道吞行、rc 属于末级管道命令），才重跑一次并改用 pipefail 或无管道形式
- 远端 CI pending 时不阻塞：用非阻塞 `gh pr checks`/`gh run view` 轮询或定时续跑，绝不在限时工具里执行 `--watch` 式阻塞命令
- 每条门禁拿到 rc+摘要且一致后立即转入下一核验项，不再为确认而重复执行

## Stop conditions
- 每项门禁都有明确 rc 与摘要行且二者一致，即下结论，不再重复运行
- 远端门禁 pending 时先输出中期审核结论并安排轮询收口，不空等

## Verification
- rc=0 且摘要行无 failed/error；rc≠0 时以日志中首个失败条目为诊断入口
- 同一门禁命令不因‘输出没看全’而第二次全量执行——这是本方法的核心检验点

## Counterexamples
- 管道命令（`cmd | grep`）的退出码属于末级命令，rc 不再权威，必须 pipefail 或解析日志内容
- 被验证的脚本恒退 0，或存在 deselected/xfail 掩盖真实失败时，必须解析摘要计数而非只看 rc
- 输出本来很短的门禁（单行 lint 结果）直接看回显即可，套文件中转反而增加步骤
