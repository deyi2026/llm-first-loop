---
method_id: terminal-state-and-blocker-holder-first-verification-48460d9af22f
name: terminal-state-and-blocker-holder-first-verification
description: 核验异步运维动作（publish/deploy/restart）是否完成时，先把未知量压缩为三跳：权威状态源做 desired vs live 比对直接定结论；对失败 action_id 沿其失败详情串中点名的阻塞资源定位持有者（锁文件 -> 持有 pid -> 进程身份）；若持有者就是发起会话的宿主进程，判定自死锁，停止会话内重试，交接带精确命令与回执落点的 out-of-band 操作者动作。禁止用 docs/日志/旧 handoff 的宽搜索去重新推导状态与事件流中已给出的结论。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6e0fb83b-03af-44ff-be33-c3498380b42f:1268:f4b31be2cf5306b90ca0
evidence_refs: learning:learn:66d650cb1aa3
created_at: 2026-09-20T21:21:31.950733+00:00
updated_at: 2026-09-20T21:21:31.950733+00:00
---
## Trigger
用户询问某异步/长时动作（重启、部署、发布）'完成了吗'或需核验终态；状态源显示 desired 与 live 不一致且 restart_required；存在带失败详情字符串的 action_id

## Discriminator
第一跳权威状态回执已同时给出 desired≠live（generation/git_head 不一致）与 restart_required=true，事件流已含失败动作的终态及详情串，且详情串本身点名了阻塞资源的类型与数量（如 'active run locks: 1'）。这已把'是否完成'确定为否，剩余唯一未知量是'该资源由谁持有'——转向 search_docs/目录枚举/旧 handoff/日志巡检不会缩小这个未知量

## Short path
- 查权威部署/服务状态，比对 desired vs live（generation、git_head、进程启动时间）：未知量=换版是否落地；不一致即'未完成'，无需重新推导
- 对每个失败 action_id 查终态与失败详情（status 按 action_id，或 event_stream 按 action_id 过滤）：未知量=失败类别；从详情串提取阻塞资源类型与计数
- 定位阻塞资源持有者：lsof 该锁文件得到持有 pid，再核对进程身份：未知量=谁在阻塞、是否与发起者自身相关
- 时间戳交叉验证（动作失败时刻 vs 最后一个 run 结束时刻）：未知量='等一会儿/结束自身 run'能否解锁；空闲窗口后仍失败则排除该假设
- 若持有者=发起会话的宿主进程 → 判定自死锁：停止会话内重试（重试只会复现超时），输出操作者交接（精确命令、回执落点、预期对话中断属正常），停止

## Stop conditions
- desired=live 且 action 终态=succeeded 且回执一致 → 回答'已完成'并停止核验
- 阻塞资源持有者已定位且与发起者宿主进程因果绑定 → 不再重试、不再宽搜索，转 out-of-band 交接
- 失败详情为瞬时错误（网络/超时）且持有者与自身无关 → 走普通重试/清理路径，不套用自死锁结论
- 用户只需结果且状态已明确、无下一步行动建议需求 → 报状态即止

## Verification
- 最终结论的每个事实均可映射到权威回执：状态输出的 live git_head、action 终态详情、锁持有 pid 的进程身份
- 用失败时间戳与'资源将释放'假设交叉核对：空闲窗口之后仍失败，才把'等待可解'判为证伪
- 交接命令附带回执落点（如 receipt 文件）与期望的新 git_head，重启后一次查询即可闭环

## Counterexamples
- 状态源显示 desired=live 且动作 succeeded → 直接答'完成'，不进入根因链，也不追锁持有者
- 失败详情是无资源占用的绑定/配置错误（如 deployment binding 的 git_head mismatch）→ 下一跳是修正 desired 绑定，与本方法无关
- 锁持有者是无关第三方（残留 run、孤儿进程）→ 自死锁不成立，正确动作是清理持有者后在会话内重试，而非强制 operator 交接
- 动作尚未到达终态/未超时 → 先等待并查终态，过早下'结构性死锁'结论会误判
