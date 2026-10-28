---
method_id: mine-gated-cli-contract-one-read-then-qualified-destructive-command-8d148edb6ddc
name: mine-gated-cli-contract-one-read-then-qualified-destructive-command
description: 对仓库本地脚本型运维 CLI（被指定为正规生命周期管理路径）执行破坏性子命令（stop/restart 类）前，先用一次权威读取提取完整调用契约：文件类型/执行位→决定解释器调用还是直接 exec；--help 中子命令分组与门控标注（如 safety-gated）→ 必带确认旗标（如 --yes）。然后一次性发全限定命令，用独立事实核验生命周期效果。本集该法可把『直接 exec 拒绝→ls/file→help→无旗标 stop 被拒→补 --yes』五步压成两步，把每轮一个未知的串行试错缩为一次读全契约。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4262a65a-bd51-4405-bed5-57af83e2e1ab:946:0c8fef509de9ec859fe1
evidence_refs: learning:learn:63a5cf54b12b
created_at: 2026-10-22T09:12:29.184914+08:00
updated_at: 2026-10-22T09:12:29.184914+08:00
---
## Trigger
准备对仓库内（非系统安装）管理 CLI 执行破坏性/生命周期子命令，且其调用方式（解释器/执行位）或门控旗标尚未确认；尤其该 CLI 是任务声明的『正规路径』，直接 kill 进程绕过它不合规。

## Discriminator
已取到的 --help 文本把目标子命令标注为门控组（本集：『start|stop|restart — launchd lifecycle control (safety-gated)』在首次 stop 之前已在屏）——门控组标注即『确认旗标存在』的可观察证据；辅以文件属性（file 显示 Python script、mode 无 +x）锁定解释器调用。两个事实一次读取即可全得，无需靠拒绝回执逐条学习。

## Short path
- 未知量=该 CLI 的调用契约：先一次读取 file/权限位 + --help（子命令分组、门控标注、输出模式），不先发破坏性命令
- 由 help 推导全限定形式：脚本无 +x → 走解释器调用（不 chmod 他人文件、不直接 exec）；子命令属 safety-gated 组 → 附确认旗标（--yes）
- 一次发出全限定停止命令；以独立事实闭环：port free/进程消失（停止）或 UP + health ok（恢复）
- 独占期结束后按同一契约路径恢复原服务并核验，全程不出现 REFUSED/Permission denied 中间态

## Stop conditions
- 契约两要素（解释器、门控旗标）已从权威读取确认，破坏性命令一次被接受
- 生命周期效果已被独立事实（端口监听/进程表/health 端点）核验
- 目标为系统级 CLI 且契约已知 → 跳过预读直接执行

## Verification
- 破坏性子命令首次发出即被接受（回执无 REFUSED / Permission denied）
- 停止后端口监听消失、进程无残留；恢复后 health ok 且 warmup 正常
- 未对目标 CLI 做任何权限位或内容修改（仅通过解释器调用）

## Counterexamples
- 系统级稳定 CLI（git/systemctl/docker）：契约早已知，预读 help 反而增加调用
- help 未声明门控或 CLI 无 help：一次受控试探的拒绝回执本身即契约信息，反而是最短路径
- 只读子命令（status/health/logs）：无副作用，可直接执行后按回执修正
- manager 的 README 才记载旗标细节而 help 省略（如 --wait-idle 需 --yes 只写在文档）：应读 README 而非止步于 help
