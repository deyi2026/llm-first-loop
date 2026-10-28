---
method_id: bounded-blocking-polls-honor-wait-and-cap-on-async-child-862e9ccee3bd
name: bounded-blocking-polls-honor-wait-and-cap-on-async-child
description: 任务书以『等待参数＋次数上限』定义异步子代理轮询预算时，把每次 subagent_result 当作消耗预算的阻塞等待并计数：非终态回执里『尚未结算；可稍后再次查询/可继续父级工作』的提示本身就是判别信号——立即原样重发同一查询是零信息忙等。轮询数到上限仍未终态即停止，按任务书失败条款如实上报 child_id 与最后回执；到达终态则原样转达结论文本，且汇报中的轮询次数陈述必须与实际回执序列可数一致。
status: active
source_model: glm/glm-5.3-flash
source_episode_refs: episode:9bd70934-bd3b-4f71-8e97-54ab103d515c:1:b84a42f5eec54402bce5
evidence_refs: learning:learn:d2ed3169bbe2
created_at: 2026-10-19T08:57:26.842278+08:00
updated_at: 2026-10-19T12:28:56.190139+08:00
---
## Trigger
编排方需轮询后台子代理/异步作业直到终态，且任务书显式给定轮询预算：等待参数（如 wait_seconds=10）与次数上限（如最多10次），并附『失败则如实报告』条款。

## Discriminator
首次 subagent_result 回执为非终态（child_state=running），且回执文本自证『尚未结算；可稍后再次查询/可继续父级工作/可 steer』；该提示与任务书的 wait+cap 同时在场，已足以判定下一步应是带指定等待的计数轮询，而非即时原样重发同一查询。

## Short path
- spawn 后按任务书调用 subagent_result(child_id, wait_seconds=指定值)；未知量：是否已到终态
- 回执 running：轮询计数+1；若计数<上限，携带同一 wait 再查（或期间执行合法父级工作），禁止原样即时重发；未知量不变：终态是否到达
- 回执终态：原样转达 child 结论文本与结构化行（如 VERDICT/P0P1/SHA256），如实报告实际轮询次数与预算消耗
- 计数达上限仍未终态：停止轮询，按『失败则如实报告』条款上报 child_id、最后回执与已消耗轮数，不越限续轮

## Stop conditions
- child 回执为终态（completed/failed）且结论已原样转达
- 轮询计数达到任务书上限仍未终态，已按失败条款如实上报，不再追加轮询

## Verification
- 实际 subagent_result 调用数 ≤ 任务书上限，且不存在连续原样重发的非终态轮询对
- 最终汇报中『第N次到达终态/未超上限』的陈述与回执序列逐条可数一致，不凭印象书写次数
- 每次非终态回执后的下一次调用与上一次可区分（携带指定 wait，或夹带其他父级工作）

## Counterexamples
- 任务书未给轮询预算、且要求最低延迟交接（如实时会话/看板），回执即时返回——此时紧密轮询可能是正确行为
- 首次轮询即返回终态——不形成循环，无需预算管理
- 回执每次携带新进展信号（rounds/tools/tokens 增长、cancel_requested 翻转）且任务要求持续监控进度——轮询本身在产出信息，非纯忙等；但显式上限仍应遵守
