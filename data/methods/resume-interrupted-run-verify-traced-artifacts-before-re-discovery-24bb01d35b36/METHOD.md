---
method_id: resume-interrupted-run-verify-traced-artifacts-before-re-discovery-24bb01d35b36
name: resume-interrupted-run-verify-traced-artifacts-before-re-discovery
description: 恢复被中断的任务时，action/event trace 本身就是权威状态清单：它逐条列出前次 run 已执行的状态变更命令与精确工件路径（写入的文件、修改的源码面）。恢复动作应直接核验这些被点名工件与工作区 git diff，而不是用文件名搜索、全目录 ls、全库内容搜索去重新发现状态，也不要对同一 ID 重复查询以补全截断。只有 trace 缺失、scope 不覆盖中断会话、或具名工件已被清理时才退回宽搜索。跑测试先探测仓库内 .venv 解释器，勿假定全局 uv 存在。用 trace 的确定性列举把'当前状态未知'缩成'核验 N 个具名工件'。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:873:ab8fea5fbddb298b6480
evidence_refs: learning:learn:62bfc27c7b49
created_at: 2026-09-23T14:36:14.386912+00:00
updated_at: 2026-09-23T14:36:14.386912+00:00
---
## Trigger
用户要求继续/恢复一个先前被中断的长任务，且系统提供 action/event trace 或等价执行历史，而当前无活动 goal 或 pending 队列为空

## Discriminator
trace 中是否已出现前次 run 的具体状态变更命令与精确产物路径（如写入的临时/测试文件路径、被编辑的源码文件名）：这一当时可见的事实把'中断前留了什么状态'从全仓搜索缩成'核验这几个具名工件 + 工作树 diff'

## Short path
- 读 evolution/任务记录与事件流，建立前次 run 的操作时间线（未知量：中断前已做了什么、停在哪一步）
- 从 trace 提取被点名的工件路径与被编辑的源码面，直接 stat/read 这些精确路径（未知量：草案内容是什么）
- 用 git status/diff 核对工作树，确认哪些源码改动已落盘且与 trace 目标集合一致（未知量：改动是否持久化、是否完整）
- 用仓库实际解释器（探测一次 .venv/bin/python，而非假定全局 uv）跑专项测试（未知量：实现是否通过机械验证）
- 测试通过且 diff 审查完成后即到达可提交状态，停止发现类动作，进入提交/登记

## Stop conditions
- 被 trace 点名的工件均已核验，且 git diff 的修改文件集合与 trace 中出现过的写入/编辑目标一致
- 专项测试与受影响面回归通过，无新增未知量
- trace 与权威 pending_actions/goal 状态矛盾时以权威队列为准，停止沿 trace 分支继续

## Verification
- git status/diff 列出的修改文件集合 ⊆ trace 中出现过的写入/编辑目标，无未被 trace 解释的改动
- 重跑专项测试确认为绿；解释器调用失败时立即改用仓库内 .venv，而不是换全局工具名重试
- 对照 trace 逐条确认前次 run 的状态变更均有落点（文件存在或 diff 呈现）

## Counterexamples
- 事件流缺失、截断或 scope 限定为当前会话而中断发生在另一会话：trace 不构成 provenance，应回到 pending_actions 或宽搜索
- trace 显示前次 run 只有只读调用、未产生任何工件：没有可核验的 provenance 边，恢复意味着重新规划而非核验
- trace 指向 /tmp 等易失路径且已被清理（工件 404）：应立即转向 git diff/源码树核验，不应反复重读已失效的 trace 路径
