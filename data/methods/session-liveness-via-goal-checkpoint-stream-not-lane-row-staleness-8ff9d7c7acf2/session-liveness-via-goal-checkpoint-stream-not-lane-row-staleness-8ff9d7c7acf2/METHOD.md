---
method_id: session-liveness-via-goal-checkpoint-stream-not-lane-row-staleness-8ff9d7c7acf2
name: session-liveness-via-goal-checkpoint-stream-not-lane-row-staleness
description: 资源级台账行（lane/锁/登记）的陈旧字段只度量对该资源的写入：version 不增、last_activity 冻结在创建时刻，与『属主会话仍活着、在同一 goal 其他面推进』完全兼容。行内自带的 goal_id/owner_session_id 就是会话级活性面的显式引用边：goal 的 checkpoint 流（兜底：按属主 id 查统一事件流）才是会话活性的裁决面。凡有『停滞/已死』论断且后续动作依赖它，先花一跳到该面核时间戳，再把两个视角分开陈述并纠错先前论断。它补足『读 lane 台账判停滞』类启发式的盲区：台账静止只能证 lane 未被更新，不能证属主停止活动。
aliases: 怎么确认另一个会话还在不在干活, 分支久没动静是不是属主掉线了, 查某个会话最近干了什么, 别把台账不动当成对方会话挂了
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d901b48e-25bf-45f0-a33f-23eaa879ddc3:341:6c356db7af462d2e7f6e
evidence_refs: learning:learn:8dee1375bdb1
created_at: 2026-11-19T01:54:15.650125+08:00
updated_at: 2026-11-19T01:54:15.650125+08:00
---
## Trigger
任务输入或在途论断（用户前提、自己早前发出的 help_request/回执、他人转述）把另一会话名下的 lane/锁/登记资源刻画为『停滞 N 小时/已死/不再活动』，且下一步动作（找属主是谁、联系、升级、回收、继续等待）依赖这个活性判断；手中已有或可一步只读取得该资源的台账行。

## Discriminator
台账行自身时间字段只度量『对该资源的写事件』：version 从未递增、last_activity==created_at 仅证明创建后无资源级更新，与『属主会话活着但不碰这条资源』完全兼容，不足以判死。同一行已显式给出会话级活性引用边——goal_id（及 owner_session_id）：goal 的 checkpoint 流才是会话级活动证据，其最新时间戳可直接证伪『停滞 N 小时』。本集中行 version=1 且时间戳冻结于创建刻，而属主 goal 的 checkpoints 显示当晚仍在按防循环合同产出并主动停手——『停滞』被判定为仅资源视角事实。

## Short path
- 用任务文本中的精确资源标识对共享台账做一次只读定位，拿全行：owner_session_id、goal_id、version、last_activity（解决『属主是谁』）。
- 把行内 version/last_activity 只当资源视角事实；即便它与『停滞』断言一致，也不下会话级结论，而是沿行内 goal_id 跳到会话级活性面。
- 读 goal 的 checkpoint 时间戳与摘要：有近期产出→会话存活且停手是合同性/选择性的；无→再用统一事件流按 owner_session_id 兜底查一次。
- 答复时把两个视角分开（资源久未更新 ≠ 属主停滞）；若『停滞』出自自己早前的 help_request 或结论，显式纠错并引用 checkpoint 证据，之后才做活性结论所许可的后续动作。

## Stop conditions
- 会话级面（goal checkpoints 或按属主 id 的 event_stream）显示近期活动 → 活性已裁决：不发『你还活着吗』类探针，不按停滞升级或回收。
- 会话级面同样陈旧且事件流兜底也无活动 → 『停滞』分类成立，转入既有的阻塞资源处置路径（dry-run 回收/带证据升级）。
- 任务只关心资源本身（回收、清理其 worktree），属主死活不改变动作 → 资源行字段已足够，跳过活性跳。

## Verification
- 活性结论必须引用带时间戳的会话级 artifact（goal checkpoint 条目或 event_stream 事件），不得用资源行自身字段自证活性或死性。
- 最终报告区分『资源视角停滞』与『会话视角存活』两个陈述；若先前断言过停滞，给出显式纠正及其证据出处。

## Counterexamples
- 资源行近期有 version 递增或 last_activity 更新 → 资源视角本身已证活跃，无需 goal 跳。
- goal 记录不存在或 checkpoints 与资源行同样陈旧 → goal 面不构成反证，须换事件流兜底后才能下结论，而非直接采信『停滞』。
- 任务就是要回收一条真被遗弃的资源/处理其脏 worktree，属主死活不改变操作 → 加活性跳是纯开销。
- 该系统中资源行与 goal 本无归属边（行内无 goal_id/owner 可跳）→ 判别器不适用，需另找该系统的会话活动面。
