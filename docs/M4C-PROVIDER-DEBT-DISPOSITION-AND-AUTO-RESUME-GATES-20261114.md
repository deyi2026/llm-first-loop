# M4-C 未决 Provider 债务处置与任意时点自动恢复门禁（2026-11-14）

## 0. 裁决与范围

**旧 M4-C：HOLD，不得复用旧预算或重放旧 Run。** 这里的“处置”是将债务**可复核地隔离并记录**，不是伪造结算、退款或声明远端计费结束。

**新 M4-D：有限 PASS** 仅覆盖特定 finalizer 时点真实 SIGKILL 后，在**全新 Session / 全新授权 / 新 Run**下完成同一文稿；不能据此宣布任意时点自动恢复 PASS。

本批次只新增只读审计脚本、合成负向测试和本文件。**未修改**原 M4-C EventStore、TaskBudgetStore、目标文稿、运行时代码、main、Mac/Deepin 服务；无 Provider/Tool 外发。

## 1. 真实样本的独立事实

- 来源：独立隔离目录 `.worktrees/t1-deliverable-resume-20261114/data/t1-process-crash-20261114/`
- 旧 Session：`b6e6d45f-f123-4728-bb2c-7d15746211ba`
- 旧 Run generation：`3ea8dcdb68f34ad7883eb483bcc3e330`
- 旧预算：`webt1-48c8667fe13d484f519aaca7325526b2`，`closed_uncertain`，revision 19
- Provider `transport.opened=3`，`transport.settled=2`；Tool 回执 2，已观测 edit_file 副作用 1；`run.end=0`
- 未决预算 reservation：`dispatch-0c7795c55e044ad8abf8bbd4f0f9cb92`，`phase=dispatched`，无结算回执
- 唯一未配对 Provider transport：`pattempt:565848dd8c5846ab8717e04ba194f25f`，对应 call `pcall:82c1ff0310f2cf937757e74b35745069`
- **证据限制**：预算 reservation 与 transport attempt 的未决配对是“唯一剩余项”推断，**不是**上游 Provider 结算证明；未决 opened 事件没有可供认证查询的远端 request ID
- 旧预算的 `physical_quiescence_verified=false`；远端是否完成、是否计费及实际 usage 均未知

| 原始证据 | SHA-256 |
|---|---|
| `state/event_logs/b6e6d45f-f123-4728-bb2c-7d15746211ba.jsonl` | `94d64a02f2c75edf13e040a11483d478a1d20cd6cc38e4b07563a6a5864590c4` |
| `state/task_budget_t1_web/budget-7368491c77ea42c0b84b09931f3cbb638678072b1c9befeec765be2a65a5a78b.json` | `3a0dfa37143e908b8aee4237cbc5745f8f2e298d4c77677de0d1b535de057881` |
| `workspace/docs/agent-production-article.md` | `68e91a859b80362f2ba4f91170377aa8b9e36878542666e17e0e96a934edc2f4` |

已部署 M4-D 只读 preflight 对旧样本返回 `HOLD/source_budget_has_unsettled_liability`、真实 exit 2；不具备新授权资格。不能用新样本的 PASS 替换这一裁决。

## 2. 最小可复核处置机制

新增 `scripts/t1_provider_debt_disposition.py`（独立候选分支；**未集成生产**）：

1. 输入原始数据目录、workspace、Session、authorization、run generation、唯一文稿及三份预期 SHA；拒绝非规范路径、符号链接、文件缺失、超大文件或身份漂移。
2. 读取真实 EventStore / TaskBudgetStore；验证 `closed_uncertain`、同一 Run generation、预算保留 3 次 Provider 与 2 次工具用量、恰好 1 个 `dispatched` 未决 reservation、两笔已结算 Provider receipt 与真实 EventStore event ID 一一对应。
3. 验证唯一未配对的 `transport.opened`、call 未结算、工具执行回执链与唯一 edit effect、目标 SHA、旧 Run 没有 `run.end`；拒绝未知动作事件、重复 event identity、伪造 settled event、错配回执、篡改预算/目标。
4. 审计前后重新计算三份证据 SHA，确认旧样本字节不变。
5. 审计成功仅返回 `audit_status=PASS_EVIDENCE_CONSISTENT` 与 **`disposition=QUARANTINED_UNRESOLVED`**，CLI **exit 2（HOLD）**；证据错误 exit 3（HOLD）。**不存在 exit 0 的放行路径**，不写账本，不退款，不签发新授权，不调用 Provider/Tool。
6. 输出 JSON 只包含关联 ID、数量、SHA、风险边界，不输出模型请求、密钥或原始文稿。

本次实样本审计回执：`data/m4c-debt-disposition-20261114/old-m4c-debt-audit.json`（位于独立候选工作树、与旧样本分离）；旧三份证据前后 SHA 完全一致。

**三种状态不得混淆：**

| 状态 | 可核验含义 | 是否解除旧 Run HOLD |
|---|---|---|
| `QUARANTINED_UNRESOLVED` | 原账本完整、未决负债被隔离、不能再调度 | **否** |
| `PROVIDER_ATTESTED`（未来） | 通过真实 Provider 官方查询/可认证回执，能精确绑定账户、请求、模型、时刻、用量/终态 | 仍需独立审查；**不能直接重放旧 Run** |
| `OPERATOR_ACCOUNTING_WRITE_OFF`（未来） | 人工财务记账/风险接受，不等于 Provider 结算事实 | **否** |

目前没有 Provider 可认证的请求级结果，故第二种状态**不可用**。不允许手填 JSON、自称上游成功、仅凭聚合账单或本地 socket 关闭来“结清”旧债务。即便将来获得证据，也只能**追加独立裁决回执**，不得重写旧事件或将旧 Run 变成自动可重放。

## 3. 验收与剩余门禁

已在隔离候选执行 17 项专项合成测试，覆盖正常 HOLD、错误 exit、三 SHA 漂移、错 Run、伪造 settlement、预算 phase 伪造、符号链接、无源写入、未知 Provider 事件、回执错配、无认证 remote ID 文本、伪造退款；Ruff、Pyright 均通过；与既有 M4-D 预检测试合计 60 项通过。真实旧样本审计 exit 2，旧三 SHA 字节一致。

仍需：独立 GLM-5.3 Reviewer 对**冻结候选**审查 PASS（P0/P1=0）、原版完整 R9 exit 0、受审查 GitHub 分支/远端 CI。门禁未完成前不合入 main、不发布、不重启。此脚本是只读审计辅助，不是生产恢复入口。

## 4. 任意时点自动恢复的下一阶段测试矩阵

必须先区分“**自动恢复事实与状态**”和“**自动重新发送 Provider/Tool**”。前者可做 fail-closed 恢复；后者必须有独立幂等性和权限证据。逐一注入真实进程终止、从持久源重建，再观察 Provider/Tool/文件副作用：

| 中断窗口 | 必需动作 | 通过条件 |
|---|---|---|
| 授权前 / 预算 reserve 前 | 恢复到未执行 | 不凭空生成授权，不调用 Provider |
| `reserved` 且有可验证 zero-send | CAS 撤销或重新评估 | 只在证实未发送时允许重新规划 |
| `dispatched` 但 transport 未确认 | UNKNOWN | **HOLD**，不得猜测 zero-send |
| `transport.opened` 到 `settled` 之间 | UNKNOWN / 隔离债务 | **HOLD**，禁止重发或退款 |
| `settled` 后、工具开始前 | 重建预算和工具状态 | 不重复 Provider，需新授权或经批准的策略 |
| 工具 started 后、effect receipt 前 | 核验目标/副作用与 CAS | 不确定时 **HOLD**，不得盲写 |
| effect observed 后、`run.end` 前 | 核对完整持久回执 | 不重写旧正文；新 Session/新授权续接需单独准入 |
| `run.end` 后 | 终态重放只读结果 | 0 次新增 Provider/Tool |
| 双 worker / 锁竞争 / 过期 nonce / 撤销授权 | 单飞、CAS、拒绝 | 绝不并行执行同一副作用 |
| SSE 断线 / Web 重启 / Provider 超时 | 事实与展示分离 | SSE 重连不触发真实重放 |

**验收门槛**：覆盖每个持久状态转移的负向测试，至少一组真实 GLM-5.3 隔离中断样本；独立 Reviewer PASS、原版完整 R9 exit 0、远端 CI 全绿，且不出现未结清债务被放行、重复写入或未授权发送。任何一个窗口证据不全，保持对应窗口 HOLD。不得将单一 finalizer 注入样本宣称为“任意时点”证明。

### 4.1 当前自动恢复的实际架构边界（源码核验）

- `src/llm_loop/core/loop/runner.py::BackgroundRunner` 将活跃 `RunHandle` 放在进程内 `_registry`，后台线程为 daemon；OS 进程死亡后该 registry 不会自动重建为可继续执行的 worker。
- `src/llm_loop/web/routes.py` 的 `resume=true` 语义是订阅**已有** run；没有 live handle 返回 `no_active_run`，不是执行恢复。
- `src/llm_loop/web/human_turn_queue.py` 已有 stale claim 机械核验：`ingress_open` 且无 `run.end` 会进入 `recovery_required`，禁止盲目重发。这项安全行为应保留，不得为“自动续跑”而退化。
- `src/llm_loop/web/queue_recovery.py` 的服务端兜底主要处理仍为 `queued` 的消息，不等于恢复已开始执行的 Provider/Tool 副作用。
- `src/llm_loop/core/loop/engine_services/run_finalizer.py` 的 `run.end` 持久化异常采用 fail-open 记录日志；任意时点恢复门禁必须独立处理“实际完成但缺终态事件”这一窗口。

**根因结论**：目前具备“状态/展示恢复与安全拒绝”的部分基础，但缺少**跨进程持久执行状态机 + 每次外部副作用的可核验幂等恢复协议**。最小实现应先把旧 Run 归入可观察的 `completed / safe-to-replan / unknown-HOLD` 三类，任何 `unknown` 不得自动 Provider/Tool 重放；不能仅把 SSE 重连改成重新调用 `run_stream`。

## 5. 下一步顺序

1. 冻结审计候选 SHA、回执与 17 项测试；交给独立 GLM-5.3 Reviewer 查验身份绑定、证据伪造与 TOCTOU。
2. 修复 Reviewer 的 P0/P1 后再跑完整 R9；核对远端 main 基线、保护并行修改，再按门禁决定是否集成。
3. **只有第一阶段门禁通过**，才在全新隔离环境做上述中断矩阵，先无外发负向测试，再申请明确限定预算的真实 GLM Run。旧 M4-C 样本始终只读 HOLD。
4. 任何生产部署、Deepin 变更、自动授权或对外发布均需另行明确批准。
