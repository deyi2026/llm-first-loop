# M4-D T1：崩溃后以新授权继续任务的最小恢复门禁（冻结设计 v1）

日期：2026-11-14。基线 `f212731bd537d46c01ebb44905979516182aa069`；隔离分支 `fix/t1-crash-recovery-admission-20261114`。

## 事实与问题

M4-C 在隔离 Web Host 真实执行一次 GLM-5.3 T1 Run：read_file 和 edit_file 各成功一次，写入效果由 EventStore 持久化证实；在 run.end 之前对 Web 子进程发送 SIGKILL (-9)。新进程能重载原会话/文件，但旧 run_generation 的 SSE resume 返回 no_active_run。崩溃时 Provider transport 3 次 opened、2 次 settled，TaskBudgetStore 留下一笔 dispatched 未决负债；原根已 CAS 保守收口到 closed_uncertain，不退款、不伪造结算。M4-C 只能证明安全停止，不能宣称自动续跑。

## 目标与不变量

1. **不复活旧 Run**：resume 仍仅订阅同进程存活的原 generation。恢复必须是操作员重新授权、全新 Session、全新 authorization_id、全新 Run；旧 root 不可 reissue/reopen。
2. **先核验再授权**：提供最小的只读操作员预检脚本，复用现有 EventStore、TaskBudgetStore 和文件 SHA；脚本不产生模型/工具调用，不修改任何原账本、Session、目标文件或配置。
3. **UNKNOWN 阻断**：任一 provider opened 无 settled、任一 reserved/dispatched/unknown 预算负债、任一 started 工具无 committed receipt、失败/中断 Provider 结果、事件/账本不一致、target SHA 漂移、授权身份不符，均返回 HOLD（非零退出），绝不自动退款、清债、补跑或生成新授权。
4. **完成状态先检查**：如果旧 Run 已有 run.end，则不是本恢复场景，返回 HOLD；已完成的文件副作用必须与 effect_observed、receipt_committed、真实目标 SHA 一致，不能根据模型文字或文件存在性猜测成功。
5. **授权边界不放宽**：正向预检仅说明“允许操作员考虑发起全新 T1 授权”，不是自动发布授权；仍由现有 0600 operator config + 单次 CAS + read_file(snapshot=true) / edit_file(expected_snapshot_ref) 执行，最多 4 次 Provider、3 次 Tool、现有时间窗口，不新增第二账本/新 API/新常驻服务。
6. **主机停止必须有人工证据**：旧 Host 的物理停机/失联和外部 Provider 终态无法由该脚本单独证明；正向预检需要显式操作员停机确认标志，报告该标志仅为声明，不能标成独立物理 quiescence 证明。
7. **安全性优先于自动化**：真实 M4-C 残留 1 笔 Provider dispatched，因此预期明确 HOLD，不能“为了演示成功”篡改旧账本或执行第二次真实 Run。

## 实现边界

新增 `scripts/t1_crash_recovery_preflight.py`（只读 CLI）与 `tests/unit/test_t1_crash_recovery_preflight.py`（合成隔离 fixture 正负测试）。复用 `llm_loop.event_log.store.EventStore`、`llm_loop.resources.task_budget_store.TaskBudgetStore`、`llm_loop.resources.task_budget_dispatch.exact_workspace_scope`。不修改 `src/llm_loop/` 运行时代码、`scripts/ci_gate.sh`、main、现有 operator schema 或服务管理。脚本应支持单次 `--json` 机器可读输出，异常默认 HOLD，不输出敏感信息。

必需输入：`--data-dir`、`--workspace-root`、`--source-session-id`、`--source-authorization-id`（32 位小写 hex）、`--source-run-generation`、`--target-path`、`--expected-target-sha256`、`--new-session-id`，以及仅正向门禁要求的 `--old-host-stopped-attested`。严禁把新会话等同旧会话；不创建新会话、配置或 Run。输出 `status=HOLD` / `status=PREFLIGHT_PASS_OPERATOR_ACTION_REQUIRED`，`eligible_for_new_authorization`，简短原因及证据摘要。无论结果如何原数据必须字节不变。

## 最小验收矩阵

- 真实 M4-C 冻结目录：`closed_uncertain` 且一笔 dispatched Provider → HOLD，零写、零调用。
- 合成“旧 Run 无 run.end、工具完成且 receipt/effect 匹配、Provider opened/settled 配对、预算无未决”的样本 → 仅当目标 SHA、身份、操作员停机声明全部符合才 PRE-FLIGHT PASS（不实际 Run）。
- 去掉停机声明、重用旧 Session、源 run_generation 不匹配、source authorization 错、SHA 漂移、symlink/path traversal、缺失或损坏账本/事件、started 未 committed、Provider 结果不确定、effect 未观测/不匹配、旧 run.end 已有 → 全部 HOLD。
- 真实的既有 T1 单次 CAS/授权撤销、原 generation SSE 订阅语义、预算单飞门禁测试不得退化。
- 变更仅文档/脚本/测试，独立 GLM-5.3 Reviewer 必须 completed/PASS/P0=P1=0；随后原版 `bash scripts/ci_gate.sh` 真实 exit 0。仅门禁全部满足才允许提交受审查 GitHub 分支；禁止合并 main、生产重启或发布，除非另获授权。

## 非目标与剩余 HOLD

不自动续跑旧 Run；不回收 UNKNOWN 的 Provider 账单；不以新 root 绕过旧 root 的未决债务；不推断外部 Provider 已终止；不自动写文件；不将“操作员预检通过”当作“生产级自动崩溃恢复”。需要更强的跨进程隔离或实际恢复执行时，先做独立设计审查再另行授权。


## 首轮独立审查与补修（同一候选族）

独立 GLM-5.3 Reviewer 对冻结 SHA `e83716cd1bb490757dbe691ade5db17f954eba29` 返回 completed/REVISE/P0=0/P1=2/P2=5。P1-1：未知 provider/tool/run 事件被忽略，错误地允许失败/中断证据下 PASS；P1-2：EventStore 与 TaskBudgetStore 仅按计数对账，无法识别已结算回执错配。修复后：

- 显式列举本门禁允许的 provider/tool/run/llm 事件，未知事件及中断事件一律 HOLD；provider.call 与 provider.transport 都要求已结算、成功并配对。
- 真实 Provider 预算 `webt1ev:<settled_event_id>:<digest16>` 与唯一的 EventStore settled event_id 逐笔绑定；Tool 预算 `dispatch-receipt-<reservation_id>` 及 tool_id 与唯一 read_file/edit_file 的 finished/committed 事实、result_state_sha256、status=success 对账。现有 EventStore 未记录 Tool reservation_id 与 execution_id 的直接交叉键，因此不伪造不存在的映射；正向门槛限制恰好一读一写、各一次。
- 事件、账本、目标文件在发出 PASS 前二次核验；EventStore 目录缺失即 HOLD，不新建；目标超过现有 T1 2MiB 限额即 HOLD。
- 以真实 EventStore/TaskBudgetStore API 合成 37 项正负/竞态测试，扩展回归 159 项 PASS；真实 M4-C 残留 dispatched Provider 仍 HOLD，源证据字节不变。

以上为只读操作员预检，不修改运行时授权边界。即使 PRE-FLIGHT PASS，也不能称为物理静默证明或已完成自动续跑；必须另由操作员创建新 Session、新 authorization_id，并通过原 T1 受控入口执行。独立复审与完整 R9 仍为后续门禁。


## 第二轮独立审查与补修

第二次独立 GLM-5.3 Reviewer 审冻结 SHA `be66fd47013cbe53865a3f2188ba893b70fa3058`，结果 completed/REVISE/P0=0/P1=1/P2=5。P1 反例为非 provider/tool/run/llm 前缀的 `operator.revoked_source_authorization`、`budget.revoked`、`plugin.execution.failed` 等异常事件可能被忽略。现改为**全事件类型显式允许清单**：除本任务验证过的必要生命周期/模型/工具/预算事件外，任何其他事件均 HOLD。新增 4 类非前缀事件负测，均返回 `unknown_evidence_event_kind`。

同步收紧：操作员停机声明在事实检查后才成为正向准入条件（真实未决债务不因缺声明而被掩盖）；复核 EventStore 前再次确认目录存在，避免缺失目录的潜在创建副作用；要求机器调用 `--json`，缺参也输出机器可读 HOLD；目标读取使用 `O_NOFOLLOW`；Provider receipt digest16 格式验证、预算 reservation kind 显式验证。新增相应竞态与参数负测。更新后新增测试 43 passed、扩展专项 165 passed；真实 M4-C 样本有无停机声明均 HOLD 且原数据不变。第三次独立审查与原版 R9 仍为后续门禁。
