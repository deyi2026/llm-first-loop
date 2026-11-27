# DESIGN-20261126 轻量主统筹 P0 补充（v2.1，SA-LIGHT-COORDINATOR-P0-IMPLEMENT-20261126）

基于 DESIGN-20261125-super-agent-nonblocking-router-v1.0.md（R01-R30/M1-M3）与用户 2026-11-26 新约束。
本文件只做增量冻结：新增 R31-R35 与验收矩阵；不改写既有条目。

## 增量规则

| # | 规则 |
|---|---|
| R31 | 主统筹角色由可信服务端配置/任务身份确定（settings.coordinator_light_role，可配置不硬编码）；职责白名单=接收、安排、只读状态、异常决策、收口；短 Run 派工后退出，不执行长命令、审查、等待、CI 轮询、Git、部署；普通聊天不受影响；保留人工应急回退（配置开关）。 |
| R32 | 已知归属确定性直达负责 Worker：任务安排落 HelpInbox durable 文件 + QueueServerFallback.poke_session 即时唤醒，全程零主筹模型调用；复用 Goal/Lane/TaskClaim 绑定，不新造路由账本。 |
| R33 | 真实审批 approved 只触发只读核验 + 来源会话唤醒；绝不视为执行权限——令牌签发/消费链路（Host verify）原样保留，resume 不得读写 token。 |
| R34 | 后台 Job 终态/退出码/精确候选 SHA 与独审资格分别核验：exit==0 且 SHA 匹配才接续；Reviewer 文字 PASS 绝不等同 R9 真实 exit0；任一权威缺失标记不可用，不假造。 |
| R35 | 幂等/CAS/同 lane 单 writer/workspace-owner-run_generation 绑定沿用既有机制；过期/撤销/未知副作用不重放；正常进度合并投影（复用 RuntimeConvergence），异常才升级主统筹；不新增数据库/守护进程/全局高频轮询。 |

## 最小真实纵切（P0-3）

接收任务（POST 任务卡）→ 持久安排（HelpInbox 文件，幂等键 operation_id）→ Worker 领取
（既有 TaskClaim/HelpInbox 语义）→ 真实无害后台任务或现有受管阶段完成 → 权威回执
（job exit0+SHA / 审批 approved 核验 / 合并 SHA）→ 下一阶段/最终确认（poke 续链）。
主统筹 Run 在派工后即释放（阻塞等待=0，架构性保证：续链由 poke/fallback 承担）。

## 性能口径（设计目标，非实测达标声明）

受理 P95≤500ms、已知路由≤1s、空闲派发≤5s、普通统筹决策≤15s 为设计目标；
既有实测参照：队列 enqueue→claim 19.9ms（gen457 实机）、本地受理→派发 P95 见
tests/web/test_super_agent_concurrency.py 口径标注。主筹阻塞等待=0 为架构性保证，
不是性能实测。部署前不宣称任何目标"已生效"。

## 验收矩阵

1. 端到端纵切（dispatch→HelpInbox→poke→job 回执→续链）零模型调用
2. 真实审批 approved→只读核验+唤醒，token 不变
3. Job exit0+SHA 匹配才接续；Reviewer PASS 不满足 Job 接续（R34 分离）
4. 4-8 并行派工卡互不串线
5. 重启/重复 operation_id/错 scope/旧代次/未知副作用不重放
6. 角色 disabled 拒绝（可配置回退）
7. RED 先行：实现前断言失败（瓶颈复现），实现后全绿为定向回归
