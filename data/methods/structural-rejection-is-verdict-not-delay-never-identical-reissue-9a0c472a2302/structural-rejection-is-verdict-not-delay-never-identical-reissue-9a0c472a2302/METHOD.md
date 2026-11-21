---
method_id: structural-rejection-is-verdict-not-delay-never-identical-reissue-9a0c472a2302
name: structural-rejection-is-verdict-not-delay-never-identical-reissue
description: 对已终态子代理结果发起的闸式调用（签发/落账类 verify）被程序以自描述确定性错误拒绝时，先分类再行动：reason 命名的是产物结构形态（如 review_not_structured=审查记录不是顶层纯 JSON）且无 pending/落账中语义，则是裁决而非延迟信号；产物是否合规在调用前就已可见（答案=多段散文+```json 围栏块≠契约要求的『纯 JSON 对象』），原样重发同一请求零信息且结局注定。唯一补救走能改变产物本身的通道（settle 前注入/Host 侧落账），不可用则按硬约束停止并如实 HOLD，回报真实 child_id、终态、拒绝原因原文。反差分支：reason 命名缺失字段→补字段后重发。
aliases: reviewer 答案是散文加 JSON 块签发被拒, 闸拒绝是结构问题不是时机问题, 同一请求重发还是被拒, 散文里的 json 块算不算纯 json, 子代理已完成签名被拒怎么办, 闸拒绝不要盲目重试
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d0c548e6-af2e-4e12-8226-ee33fa4556a8:18:5bf4acd419d68794577b
evidence_refs: learning:learn:2661eeb61709
created_at: 2026-11-17T14:31:39.569573+08:00
updated_at: 2026-11-17T14:31:39.569573+08:00
---
## Trigger
异步审查子代理已到达 completed 终态后，其结果上的下游闸式调用被确定性拒绝，reason 自描述并指向产物结构/登记形态而非瞬态；或闸前机械核对契约形态条款（如『返回纯 JSON 对象』）时发现子代理答案为散文报告+围栏 JSON 块，不满足。

## Discriminator
当时已可见的两条事实：(1) 子代理回执中答案全文是多段散文审查+末尾 ```json 围栏块，不是顶层可解析纯 JSON，而契约逐字要求『纯 JSON 对象』；(2) 拒绝码 review_not_structured 直接命名产物结构，不含 pending/延迟/稍后重试类措辞。二者一一映射→结构性裁决，重发同形请求必然同果。

## Short path
- 拿到子代理终态回执后，先机械核对契约的形态条款：答案体是否为单个顶层可解析 JSON（无包裹散文、无代码围栏）
- 不满足→闸前提未达成；若已被拒，把拒绝分类为结构型（命名产物形态/登记态）或瞬态型（带 pending/超时语义）
- 结构型→不重发同一请求、不虚构『落账延迟』假设；补救只走能改变产物本身的通道（settle 前 steer 注入/Host 侧结构化落账）；无可用通道则按『任何异常即 HOLD』停止
- 报告 HOLD 时给出真实 child_id、终态、拒绝 reason 原文，以及未做动作清单（无签发/无 request_id/无手写账本）

## Stop conditions
- 收到确定性结构型拒绝后，禁止原样重发同一调用
- 形态条款核对不通过且产物已不可变（child 已 settled）：直接进入 HOLD/异常分支，不再发起闸式调用
- 存在能改变产物的通道（steer 未关闭）：切换到补救分支而非重发或 HOLD

## Verification
- 把拒绝 reason 逐字映射到更早回执中已可见的产物属性，映射成立（形态缺口↔拒绝码）才可判为结构型
- 若已发生重发，检查其输入是否零变化：两次相同拒绝=结构型确认（属事后确认，正确动作本应是跳过重试）
- 终局报告不含伪造 request_id、不含手写账本或模拟审批

## Counterexamples
- 子代理答案已是顶层纯 JSON，闸却仍拒 review_not_structured→缺口在闸侧登记管线而非产物，『落账滞后』是合理假设，一次有界等待+一次重试成立（本方法判别器不满足，不适用）
- 拒绝 reason 带瞬态语义（pending 落账、超时、限流）→有界等待后重试是正确分支
- child 尚未 settled 且 steer 通道开放→正确动作是注入式格式纠正（把『输出必须是顶层纯 JSON 无围栏』写进子代理），而不是提前 HOLD
