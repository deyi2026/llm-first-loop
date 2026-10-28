---
method_id: recheck-live-lifecycle-state-before-state-gated-command-1d5dbfaa8beb
name: recheck-live-lifecycle-state-before-state-gated-command
description: 组装一条仅在特定生命周期状态才合法的命令（如完成登记类 CLI 仅接受 executing）时，若手头状态来自带捕获时间戳的检索快照或上一轮自己给出的结论，先把它当下界而非现值：读权威存储的 live 条目 status 与人工审批/override 字段，用审批时间点附近的时间窗 git log 佐证阶段，再据此推导命令。快照自述『等待人工决策』即证明状态按设计可被异步推进。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bdef5a5c-f7b7-4210-bbeb-937ff781de09:136:4f74065a0f4bb151da99
evidence_refs: learning:learn:73b750f46ae4
created_at: 2026-10-22T07:39:05.566511+08:00
updated_at: 2026-10-22T07:39:05.566511+08:00
---
## Trigger
需要给出或执行一条其合法性被记录生命周期状态门控的命令/下一步指引，而当前唯一状态来自带时间戳的检索快照或先前轮次结论，且存在异步人工审批通道可能在快照捕获后推进状态。

## Discriminator
快照自带捕获时间戳，且其内容自述等待人工决策（或已知存在异步审批通道）⇒ 该 status 是易变快照；权威 store 文件 mtime 晚于快照时间戳则确证状态可能已推进。现值只能来自 live 条目的 status 及审批/override 字段，不能来自检索索引或记忆。

## Short path
- 从检索命中取记录 id、处理工具名、快照时间戳；明确快照 status 不是现值
- 用作用域受限 grep 定位 handler 代码，从其 store 字段读出权威存储路径（不做全量扫描或按目录名猜存储位置）
- 读 live 条目：现值 status + 人工审批/override 字段及时间戳；store mtime 仅作触发怀疑的信号
- 若状态近期被人工推进，用审批时间点附近时间窗的 git log 定位落地 commit，确认实现存在及 push 状态
- 从仓库内既有用法范例（调用同一 CLI 的脚本）或 cli help 逐字确认命令形态后输出，并如实披露残留事实（如实现 commit 尚未 push）

## Stop conditions
- live 条目状态已读出，所给命令的前置状态与之匹配
- 命令入口与参数在仓库用法范例或 CLI 帮助中逐字存在
- 状态字段与 git 时间窗佐证一致，无互相矛盾的时间线

## Verification
- 重新 grep live store 中该条目，确认 status/审批字段与命令前置条件一致
- 命令引用的子命令与参数形态可逐字回溯到仓库内范例或 cli help
- 对状态推进给出双源证据：store 条目字段 + 对应时间窗的 git commit

## Counterexamples
- 命令不依赖记录状态（纯只读查询、静态事实）→ 无需新鲜度核查，直接回答
- 快照之后无异步写入可能（无人工审批通道、store mtime 不新于快照）→ 快照可当现值
- 共享 JSONL 的 mtime 变新仅因其他条目追加 → mtime 不能证明本条目变化，仍须读 live 条目本身
- 记录无生命周期维度（静态文档、一次性事实）→ 无状态可推进，方法不适用
