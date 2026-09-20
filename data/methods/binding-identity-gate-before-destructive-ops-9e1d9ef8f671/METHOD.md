---
method_id: binding-identity-gate-before-destructive-ops-9e1d9ef8f671
name: binding-identity-gate-before-destructive-ops
description: 对破坏性操作（kill/清理）的目标 ID 先做存在性检查，并把检查结果当作硬分支：零命中意味着 ID 类别判断错误（如把端口当 PID），必须先经映射证据（lsof 端口→PID）重建真实目标并核对命令行归属，再执行；命中且归属匹配则直接执行。不分支的'装饰性 pre-check'不算门控。本卡片只覆盖破坏性操作的身份门控，不构成绕过工具策略门控的依据。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:156:34f6ed1799b999ceb95c
evidence_refs: learning:learn:172f7b1c777c
created_at: 2026-09-20T08:55:00.608028+00:00
updated_at: 2026-09-20T08:55:00.608028+00:00
---
## Trigger
用户要求清理/终止一组数字标识（如 45918/62427），且当前证据未直接确认它们是 PID 还是端口。

## Discriminator
杀前同一命令内 `ps -p 45918,62427` 已返回零行（表头下无任何进程），该事实在 SIGTERM 执行前即已可见；且任务上下文本就是浏览器调试端口（9222），提示这类数字更可能是端口而非 PID。

## Short path
- 未知量：45918/62427 是 PID 还是端口？先单独跑存在性检查（ps -p），空结果 ⇒ 排除 PID 假设
- 按任务上下文假设为 debug 端口 ⇒ lsof -iTCP:<port> -sTCP:LISTEN 映射到监听 PID（98741/63901）
- 杀前核对：ps -p <pid> -o command 确认 user-data-dir 与待清理目标匹配（browser_mount_test / .worktrees），排除误杀 9222 实例
- kill 已核对 PID（含确认由其拉起的父 shell 98739）
- 验证两端口无 LISTEN、目标 PID 消失、9222 实例仍在，停止

## Stop conditions
- lsof 对目标端口返回无 LISTEN（exit≠0）且 ps 确认目标 PID 已退出
- 任一候选 PID 的 command line 不在用户指定的清理范围内时，停止等待澄清而非继续

## Verification
- 杀后复查 lsof 两端口：应无监听（对应本次 lsof_exit:1）
- 复查剩余带 debug-port 的 chrome 主进程：只剩用户在用的 9222 实例

## Counterexamples
- 杀前检查已返回匹配行且 command line 含预期 user-data-dir ⇒ 直接杀，重新映射只会浪费一轮
- 空结果本身即目标（验证进程已死/清理已完成）⇒ 空 ps 是成功信号，不是'换解释再杀'的触发器
- 证据或用户已明确标注这些数字是 PID ⇒ 直接使用，不必改走端口映射
- 目标是非破坏性读取（如查询端口占用）⇒ 无需同等级硬门控
