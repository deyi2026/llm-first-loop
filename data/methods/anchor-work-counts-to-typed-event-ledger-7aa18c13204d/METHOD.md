---
method_id: anchor-work-counts-to-typed-event-ledger-7aa18c13204d
name: anchor-work-counts-to-typed-event-ledger
description: 当需要量化或核验“某时间窗口内引擎/模型实际跑了多少工作”时，直接用带身份字段（round/run/model/duration）的类型化事件台账按窗口过滤计数；禁止把更繁忙的相邻日志（HTTP access/SSE/heartbeat）的行数当作工作单位。对“比以前慢/行为变了”类问题，把机制健康（每轮延迟趋势）与使用组合变化分开归因。
status: candidate
source_model: glm/glm-5.3
teacher_refs: method:method-self-distill-root-cause,method:method-self-distill-repo-api,method:method-self-distill-ab
source_episode_refs: session:2274a444-654d-46a3-a72b-2d83058b2289
created_at: 2026-09-09T18:12:08.139223+00:00
updated_at: 2026-09-09T18:12:08.139223+00:00
---
trigger:
- 用户报告“比以前慢/行为变了”，或需要回答/核验“窗口 W 内跑了哪些 run、多少轮”
- 环境中同时存在：带 ts+round/run 标识+model 的类型化事件台账，和更繁忙的相邻日志（HTTP access、SSE、heartbeat）

discriminator:
- 台账事件与工作单位 1:1 且携带身份字段；相邻日志行是另一种单位（混入轮询/静态/SSE），行数≠工作量——这是进入计数前即可观察的事实

short_path:
1. 先把争议窗口钉在台账上：按 ts 过滤 request/run 级事件，得到真实轮数与时长；“零轮次”是合法且决定性的结论
2. 报任何数字前声明其来源与单位；若来源行与工作单位不是 1:1，丢弃该计数或改为按身份键 join
3. 相邻日志只用来解释“用户为何感知到活动”（如前端轮询流量），永远不用于计数工作量
4. 机制健康：从台账相邻 request 时间差计算每轮延迟，按日期/模型看 p50/p90 趋势；平稳即排除机制回归
5. 组合变化：从台账按日期统计模型/任务组合，检查“以前”与“现在”是否本就是不同群体（mix shift 而非 regression）
6. 三项事实（窗口真相、延迟趋势、组合变化）齐备即停

branch_on_evidence:
- observation: 台账窗口内无 request/run 事件
  next: 结论为“该时段引擎零活动”，再到相邻日志分类那些行是什么（轮询/静态），而非寻找“漏掉的 run”
- observation: 每轮延迟按日期平稳，但模型组合变化明显
  next: 归因为使用群体变化，停止挖机制回归
- observation: 延迟趋势确有抬升
  next: 才转向代码/配置变更时间线排查

stop_conditions:
- 窗口内活动已由台账裁决（含零活动结论）
- 延迟趋势与组合变化均已量化并完成归因

verification:
- 对每个将报告给用户的数字复述“来源 + 单位 + 是否与工作单位 1:1”
- 用台账身份字段重算争议计数；相邻日志仅做行类型分类旁证

anti_patterns:
- 把更繁忙日志的窗口行数当作请求数/轮数报告给用户
- 台账无事件时拒绝接受“零”，转而猎取其他日志以“找到”那次活动

programizable:
- 按事件 type+ts 窗口过滤台账并输出轮数/run 数；报告前执行“来源单位 1:1”机械检查

model_owned:
- 判断哪个源对用户语义问题具权威性；把相邻日志行归类为工作信号还是噪声

why_shorter: 单位匹配的台账查询一步替代多日志绕行，并从源头避免制造随后需要公开撤回的虚构 run。

falsify_note:
- 反例1：问题本身就是 HTTP 流量/前端轮询量 → access 日志才是正确单位，台账会低估
- 反例2：不存在类型化台账 → 只能先按 method/path 过滤相邻日志再计数
- 反例3：台账已知丢事件 → 必须双源对账，而非单信台账
