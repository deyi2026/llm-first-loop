---
method_id: fresh-resolve-mutable-shared-state-before-bound-mutation-086c24b92de0
name: fresh-resolve-mutable-shared-state-before-bound-mutation
description: 对共享可变状态（desired deployment 代次/身份、被其他 worktree 持有的分支 ref）发起绑定性变更前，绑定值必须来自'动作前一拍'的读取，而非本回合早期或上一轮的快照。本回合两类失败同源：用陈旧 gen35 排队 restart 连续两次被 generation conflict 拒绝（35→36→37），而控制面行动记录早被读到 'desired deployment advanced while waiting' 的在案失效模式；强推 main 则因未先解析持有 worktree 而 exit 128。冲突拒绝的语义是'状态已前移，请重读'，正确响应是重读一次并按最新值重排，而非转入根因排查。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:483:4f3760a44778c32498ef
evidence_refs: learning:learn:6e1226dfcb78
created_at: 2026-09-18T17:19:52.486953+00:00
updated_at: 2026-09-18T17:19:52.486953+00:00
---
## Trigger
即将发出必须绑定共享可变状态版本/身份/持有者的变更动作（restart/apply 绑 deployment generation、更新共享分支 ref 等），且绑定值取自较早步骤或上一回合的快照，或绑定值读取与动作发起之间隔着耗时步骤（合并、测试、构建）且存在其他写入者。

## Discriminator
知识时点判别：控制面自身行动历史中已存在同类失败记录（如 'desired deployment advanced while waiting: action deployment_id no longer matches desired'），即失效模式已被在案证明；同构情形：git worktree 列表已显示当前 worktree 不在目标分支上，则更新该 ref 前必须先定位其持有 worktree。

## Short path
- 先完成不需要绑定的本地工作（审查 diff、验证分支拓扑、合并、跑测试、重建 artifact），期间不触碰控制面。
- 排队/发起前一拍重读 desired 状态记录，解析当前 generation/identity（或定位目标 ref 的持有 worktree 并确认其干净）——未知量：我的绑定值现在仍成立吗？
- 用刚读到的值发起动作；不再引用本回合早期或上轮快照中的代次/身份。
- 若收到 generation/deployment 冲突拒绝：视为并发发布者活动的证据，重读一次并按最新值重排；若再次前移，按最新观测值绑定一次并在汇报中注明竞争，而非转入故障排查。

## Stop conditions
- 动作被接受，且其绑定的 generation/identity/持有者与紧邻发起前那次读取的值一致。
- 连续冲突表明 operator 正在活跃发布：终止重试循环，按最新值绑定一次或明确推迟并上报竞争。

## Verification
- 行动记录状态为 accepted/waiting，且 deployment_generation 等于排队前最后一次读取值。
- 最终汇报中不出现来自早前回合、未经本次重读即用于绑定的代次/身份。

## Counterexamples
- desired 状态在窗口期内单写者且不可变：预读绑定即可，无需动作前重读。
- 动作 API 原子解析当前状态、不接收绑定字段：直接发起，冲突重试一次即可，重读无增益。
- 读取代次的成本远高于一次 fail-closed 冲突重试且并发发布罕见：以冲突拒绝充当新鲜度检查反而更省。
