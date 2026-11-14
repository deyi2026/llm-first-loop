# M5-A：跨进程持久 Run 事实与只读恢复裁决（最小实现）

状态：**隔离候选；尚未接入生产执行入口；不能据此启用自动续跑。**

基线：main `71f95724459f5d0500a0d19405d9a51d7586d741`。隔离分支：`feat/m5-durable-recovery-20261114`。旧 M4-C Provider 未决债务继续 HOLD，原 EventStore/TaskBudgetStore/文稿三份 SHA 不变，不复用旧 Run。

## 1. 范围与事实源

- 仅为现有 `EventStore` 增加 opt-in 的 `append_durable_run_fact`。不改变旧 `append`、`run.end`、`append_durable_human_message` 的默认行为。
- 仅支持 T1 Web 单 Run 授权（`webt1-<authorization_id>`），并核对现有 `TaskBudgetStore` 的授权、`session_id`、`run_generation`、预算 revision 和已停止状态。
- 只读 `assess_durable_run` 从事件源文件原始字节和预算真值源进行双重快照校验；不引入第二账本，不创建新授权，不启动任何 Run。
- `ToolExecutionJournal` 的 `effect_prepared`、`effect_observed` 和 `effect_snapshot` 仍为副作用事实源；SHA 匹配不证明因果归属。**本批不尝试对含任何外部动作的 Run 作正向恢复裁决。**

## 2. 严格持久化协议

新事件：

1. `run.durable.opened`：绑定 Run generation、authorization、budget id、revision。
2. `run.durable.admission_fenced`：仅在**真实执行入口已经接线并强制所有外发动作先取得持久化准入**后才能由受信代码写入；本批未在任何运行入口签发此事实。
3. `run.durable.terminal`：声明 `completed` 或 `aborted_before_dispatch`，绑定预算终态 revision；`completed` 必须引用精确的 `run.end.event_id`。

新接口以严格跨进程 `flock`、无符号链接文件打开、文件和目录 `fsync`、独立 EventStore 回读确认写入。写前失败抛 `EventDurabilityError`；一旦尝试物理追加，持久化结果不能证明时抛 `EventCommitUncertainError`。**UNCERTAIN 绝不允许盲目重写事件或重新外发。**

注意：上述协议事件本身不构成授权；预算准入、Provider transport 和 Tool effect 的物理边界必须由下一批真实代码接线。离线合成测试可以制造正向三态样本，不代表真实生产 Run 已具备该保证。

## 3. 恢复三态（只读）

| 裁决 | 必须具备的证据 | 权限 |
| --- | --- | --- |
| `completed_verified` | 严格 opened/fenced/terminal 三事件、关联的 `run.end` 为 completed、无任何外部活动、预算无 reservation 且 phase=stop_requested、revision 一致 | 仅报告完成，不触发新调用 |
| `safe_to_replan_verified` | 严格三事件、终态为 `aborted_before_dispatch`、无 Provider/Tool/其他活动、预算无 reservation 且 phase=stop_requested | 只说明可另行申请**新授权**重新规划；旧 Run 不能重放 |
| `unknown_HOLD` | 任何缺失、损坏、身份漂移、并发修改、未归属的前序活动、Provider/Tool 活动、未结预算、无严格终态或副作用因果不明 | 不自动重试、不重放、不放行 |

`auto_resume_allowed=false` 和 `old_run_replay_allowed=false` 对全部裁决恒成立。

前序事件还必须仅含 `session.created` 或 `message.appended(role=user)`；同一 Session 的早期 Provider/Tool/其他未知事件不能自动归因到其他 Run，统一 HOLD。预算 `closed_uncertain` 即使 reservations 为空也不能给出零副作用正向裁决。

为了先守住安全边界，本批只支持**零外部动作**的正向裁决；即使 Provider 已有本地 settled、Tool 文件 SHA 与预期一致，也一律 HOLD，等待后续实现精确的账本-事件-回执关联。旧 M4-C 不具备 M5 严格事件，仍 HOLD。

## 4. 本批负向验收

`tests/unit/test_durable_run_recovery.py` 包含：

- 缺预算、预算仍 active、预算 revision 漂移、历史 reservation；
- Provider call/transport（即使 settled）、Tool prepared/observed（即使目标文件内容吻合）；
- 旧 run.end、缺/重复 terminal、错误 generation、未关联 run.end、run.end 在 fence 之前、terminal 之后的新活动；
- EventStore 原始 JSONL 损坏、截断、seq 跳号、event_id 重复；
- 非法事件类型、禁用 EventStore、hook 过滤、写前文件打开失败、写后 fsync 不确定、符号链接拒绝；
- 独立进程写入 opened/fenced 后非正常退出，再从全新进程对象读取；双进程严格 append 的 seq 不重复；
- 两种离线**零外发**正向判定，确认它们不赋予自动重放权。

## 5. 下一批必须完成的缺口

1. 将严格 Run 事件接到实际 Web/T1 受控入口，在取得真实 session lease、授权 nonce 和预算 CAS 后才 emit opened/fenced；任何 Provider transport 或 Tool effect 必须先有可独立核验的持久化准入，失败即拒绝。
2. 对接 Provider `call/transport`、`TaskBudgetStore` reservation/settlement 与真实远端 receipt；远端无法证明的 UNKNOWN 必须 HOLD。
3. 对接 Tool `effect_prepared`/`effect_observed`、目标 SHA/CAS、lease/fencing generation、`receipt_committed`；物理文件变化不等于执行因果已确认。
4. 实现重启后只读查询展示，`HumanTurnQueue` stale reaper、SSE 重连不得触发旧 Run 自动重发；补双 worker、授权撤销和进程 SIGKILL 各窗口负向测试。
5. 仅在冻结候选独立 GLM-5.3 Reviewer 完成 PASS（P0/P1=0）、原版完整 R9 真实 exit 0、GitHub 远端 CI/A.5/隐私扫描通过后，才可讨论合并 main。Mac/Deepin 发布与重启需另行授权。

**禁止将本批专项测试 PASS 描述为 M5 全链路完成、旧债务解除或生产自动续接通过。**
