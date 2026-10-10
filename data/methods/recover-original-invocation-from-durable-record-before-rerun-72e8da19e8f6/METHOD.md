---
method_id: recover-original-invocation-from-durable-record-before-rerun-72e8da19e8f6
name: recover-original-invocation-from-durable-record-before-rerun
description: 后台任务失联/失败需要重跑时，原任务的准确定义（workdir、完整命令行、历史时长与结果基线）通常已持久化在任务回执/evidence 中，回执里的 durable=true/state_durable=true 就是显式信号。此时凭记忆重建路径是在未验证假设上执行：本集记忆路径 /home/svc/lfl-agent 直接失败，真实路径 /Users/yyj/Project/llm-first-loop-mirror 花了 1 次失败命令 + 宽枚举 + 2 次搜索才找回，而正确路径的一次定向检索即可同时取回路径、命令和历史基线（exit=0、7316 passed、313s），后者还直接给出重跑排程时长。与 resume-continuation 方法不同：那针对极简'继续'指令的状态重建，本方法针对失联任务重跑前的调用参数恢复。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8edca76a-022e-442c-9819-960bcdff7f8a:1166:da1a3540d4b02a504e26
evidence_refs: learning:learn:65bce81d2690
created_at: 2026-10-10T07:43:28.208021+08:00
updated_at: 2026-10-10T07:43:28.208021+08:00
---
## Trigger
后台/异步任务失联、句柄丢失或失败后需要重跑，回执显示 durable=true/state_durable=true（任务定义已持久化），且正准备凭记忆写出 workdir 或命令行来重新执行。

## Discriminator
回执中的持久化标志本身：state_durable=true 意味着原始 workdir+完整命令行可从任务记录/evidence 检索取回；任何凭记忆给出的路径此刻只是未验证假设（本集记忆路径与真实路径完全不同，属跨环境串扰，而同会话记忆中的 commit hash 却是对的——记忆部分正确恰好诱发了盲目信任）。

## Short path
- 读失联任务回执：确认 orphaned + 0 行输出 → 结果不可核验需重跑，同时记录 durable 标志作为可恢复性信号
- 先做一次定向检索（按任务源 execute_command/job_output 与时间窗）取回原始调用的完整命令行与 workdir——一次检索同时解决三个未知量：确切路径、确切命令、期望时长/输出形态
- 在取回的 workdir 上核验当前状态（git rev-parse/branch，确认目标提交未变）
- 原样重跑取回的命令（后台），并用记录中的历史时长设定检查提醒
- wake 后按预声明分支处理（绿→收口；仍在跑→只报状态再等；失败→停下分析），exit code 必须取自测试进程本身

## Stop conditions
- 已从持久记录取回原始调用并与当前目标一致（路径、命令、基线时长齐备）——停止检索，进入核验/重跑
- 记录中检索不到命令或 workdir——不静默猜测：显式声明重建假设或询问用户
- 重跑已启动且验证点/提醒已排定——停止额外动作等待结果

## Verification
- 重跑命令字符串与持久记录中的原命令逐字一致（workdir、解释器路径、参数、输出处理）
- 执行前在取回路径上核验 git HEAD/分支与预期一致
- 管道命令需从测试进程本身取 exit code（pipefail/PIPESTATUS），否则 tail 类末端命令的 EXIT=0 会掩盖真实失败
- 用记录中的历史结果（通过数、时长）作为重跑输出的对照基线

## Counterexamples
- 无持久记录可查（durable=false、输出已丢失）：本方法前提不成立，只能显式重建并声明不确定性，不能假装记录存在
- 重跑本应与原命令不同（原命令本身有错，或路径/分支已合法变更）：持久记录仅作 diff 基线，不逐字复制
- 记录中的路径指向已被有意迁移/改名的环境：沿用前必须对当前文件系统与 git 状态核验，不能盲目 cd 后长跑
