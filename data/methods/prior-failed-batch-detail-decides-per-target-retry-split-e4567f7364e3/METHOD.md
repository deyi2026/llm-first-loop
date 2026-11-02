---
method_id: prior-failed-batch-detail-decides-per-target-retry-split-e4567f7364e3
name: prior-failed-batch-detail-decides-per-target-retry-split
description: 重发多目标控制面操作（重启/发布生效）前，若状态回执已给出此前同操作批量 action 的 id 且 status=failed，第一步不是照原样重发批量，而是读该 action 记录并按失败拓扑分类：失败可归因到单一/部分目标（如 target still busy: active run locks）⇒ 拆成逐目标独立 action，一个目标忙或等门不再拖死其他目标，并跳过 live manifest 已在 desired 上的目标；失败是全局性原因（desired 缺失、代码根不存在、准入屏障）⇒ 拆分无用，先修前置。受理≠完成：按 action_id 逐一核终态，用 live manifest（新 pid + 目标 git_head）验证；承载会话的目标进入等待 requester 退出的门时，确认挂起即收尾。
aliases: 批量重启失败后再试一遍, 整批重启被一个服务拖住, 上次重启失败先查原因再重发, 分开逐台重启服务, 多服务生效要各自重启吗
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fd308b28-18c0-4929-b777-f1783be9298c:6253:37432a07e7a539b481e1
evidence_refs: learning:learn:dbba8a5a6522
created_at: 2026-10-31T11:02:54.443446+08:00
updated_at: 2026-10-31T11:02:54.443446+08:00
---
## Trigger
用户要求对多个受管服务执行同类控制面操作（如“其他的也要重启生效”），且首轮状态回执中已可见同操作的既有批量 action status=failed

## Discriminator
失败记录 detail 的拓扑在当时已可读：失败是否可归因到单一/部分目标（busy/lock/单目标错误）而非全局前置缺失。局部或异构失败 ⇒ 逐目标拆分；全局失败 ⇒ 不拆。这条事实在重发决策前就已存在，无需盲试。

## Short path
- 从状态回执钉住失败 action_id 与各目标 live manifest 差距；不盲重发批量，也不先做全目录枚举
- 用父目录一次 keyword-grep（action|deploy|restart）定位 svc-*.json 记录并直读 detail；不猜子目录名、不把命令输出管道进解释器
- 按 detail 分类失败拓扑：局部/异构 ⇒ 逐目标发独立 action，manifest 已在 desired 上的目标直接跳过不重发
- 等一个物理窗口后按各 action_id 查终态，并用 live manifest 验证新 pid + git_head==desired
- 承载会话的目标若进入 waiting_for_requester_exit：确认门已挂起、向用户交代机制后收尾，不在会话内继续等它生效

## Stop conditions
- 所有已发起 action 均查到 succeeded/failed 终态，且完成目标的 live git_head==desired
- 唯一剩余目标处于等待 requester 退出的门：已确认挂起并告知用户即可停止
- 新失败的 detail 显示与上次不同的全局原因：停下重新分类，不继续按同形拆分发

## Verification
- 逐 action_id 查 status 终态，不把受理回执当作完成
- 每个完成目标核对 live manifest：pid 更新、git_head 等于 desired 绑定 head
- 上次 failed detail 中的失败条件在本批不再成立（单目标 busy 不再阻塞其他目标、run lock 已释放）

## Counterexamples
- 失败 detail 是全局性的（desired deployment 缺失、code_root 不存在、准入屏障未过）：拆成逐目标只会得到 N 个同样失败，应先修全局前置
- 失败纯属瞬态且已消失（锁已释放、全部目标空闲）：单次批量重试更省，拆分反而增加核对成本
- 操作语义要求多目标同代原子切换（必须一致 generation 才正确）：逐目标异步生效会制造不一致中间态，不应拆
