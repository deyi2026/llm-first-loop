---
method_id: write-scope-excluded-target-delegate-minimal-safe-user-commands-dc4cdae7401d
name: write-scope-excluded-target-delegate-minimal-safe-user-commands
description: 任务必需变更的唯一合法执行者落在沙箱写范围外的仓库时：一次可逆探针钉死边界后不再试探写侧通融（解释器管道类补偿动作会被安全硬阻断），先核对机制是否接受范围内替代（与权威仓共享 git-common-dir 的可写 worktree），无替代则把变更压成最小且内在安全的命令序列交用户执行——脏文件用 stash 而非 checkout --，合并用带祖先证明的 --ff-only，用户执行不可能产生合并节点或丢数据——并声明执行后由己方接管验证（live==desired、release 身份）。
aliases: 沙箱写不进去怎么合并, 目标仓没写权限怎么发布, 让用户帮忙跑几条命令, mirror 仓 touch 被拒之后, 写范围外仓库交接给用户
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:1713:f998e4e7721791ac1950
evidence_refs: learning:learn:cef25194c0c9
created_at: 2026-10-28T08:36:07.790626+08:00
updated_at: 2026-10-28T08:36:07.790626+08:00
---
## Trigger
一次可逆写探针（touch+rm）对权威/运行时仓库返回确定性权限拒绝（Operation not permitted/NOT_WRITABLE，非超时或瞬时错误），而任务完成机制（合并、publish、restart）要求变更该仓库的 .git 或工作区

## Discriminator
写探针回执是权限拒绝而非瞬时故障，且已从机制源码/脚本核对到身份约束（如 dual-root 检查只接受与 runtime root 同一 git 身份的执行者）——两个事实同时在场即可把『还能否自己动手』一次归零，禁止继续枚举写侧绕行

## Short path
- 一次可逆探针确认写边界；回执为权限拒绝即定论，不重复试探写能力
- 核对机制约束：是否存在写范围内、与权威仓共享 git-common-dir 的可写 linked worktree；有则改用它直接执行
- 无替代时把必需变更压成最小命令集交用户：脏文件用 git stash（可恢复）而非 checkout --；合并用 --ff-only 并附祖先关系证明，确保用户执行不可能产生意外合并节点或数据丢失
- 声明执行后由己方接管的验证项（generation 递增、live==desired、release .git 身份指向权威仓），然后停止动作等待用户回执

## Stop conditions
- 用户回执命令全部成功（--ff-only 未产生新 merge commit）
- 写边界变化：获得该路径写权限或 escalation 一次性令牌
- 发现满足身份约束的写范围内替代 worktree，改由己方执行

## Verification
- 回执中合并后 HEAD 是目标 main 的直系后代且无新增合并节点
- stash 条目按名可恢复，未使用破坏性清理
- 随后 publish 物化的 release 的 git-common-dir 与 runtime root 的 .git 一致，restart 通过 dual-root/身份检查

## Counterexamples
- 存在与权威仓共享 git-common-dir 且在写范围内的 linked worktree：直接从它执行，不需要委托用户
- 写探针实际成功——边界被误判：应直接自行执行，不委托
- 被拒的是安全策略硬阻断类操作（如管道直连解释器）：走 escalation_request 提权审批，而不是改写成用户命令绕行或一律委托
