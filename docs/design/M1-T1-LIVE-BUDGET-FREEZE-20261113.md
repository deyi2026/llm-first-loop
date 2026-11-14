# M1 T1 真实执行预算与写入策略冻结 v2

状态：**准入冻结 / 待能力验收**。本文件不是开发或发布资格，也不是自动打开预算授权。

## 范围、身份与继承

- 父 Goal：`cc85f7c4-7e19-49fb-ade3-91186ace3799`；LFL Goal：`GOAL-20261113-b6d17fa0`。
- 首批只做一个 **FX05 合成资料文稿修订** 纵切：已有文件快照、精确 CAS 定点修改、结果 SHA / 段落不变性、停止后拒绝写入、断点恢复需重授权。
- 开发者：唯一 LFL `glm/glm-5.3`；最多三名独立只读调查员，独立 Reviewer 不参与实现。禁止真实外发、公开发表、跨仓写入与生产故障注入。
- 干净工作树：本工作树从 `origin/main` `93d009878412db15495aecaf19db9970eb850fad` 精确创建。旧原型 `m1-t1-writer-20261113`、其两次提交、失败尝试、预算补偿及 `bgt-t1-m1-002` 的持久 `stop_requested` revision 27 **只读保留**，严禁解锁、reset、删除或计入新成功率。
- 目标主机：本次连接的 Mac；仅发布审核通过的 Web、Feishu、Learning、WeCom（service_control all 物理仅覆盖前三个，WeCom 必须独立重启）。生产现状 gen 407 / 55e9e810c，未发生本项目发布。

## 新预算根的独立上限

- 每个**全新持久预算根 / exact Session / exact Run generation**：物理 Provider attempts ≤3，实际 Tool invocations ≤200（当前 FX05 原型进一步收紧至 ≤8），payload bytes ≤2 MiB，运行窗口 ≤30 分钟，GLM 单模型，不允许递归子代理、wake、shell 写入与跨工作树写入。
- 总输入+输出 token ≤400,000，**包含缓存命中的输入**，不能减去 cache-hit 再声称未超限。费用未知时费用判定为 unknown。
- 真实 Token 口径以 Provider 返回用量和 Host `request.usage` 的可验证物理请求回执为准。必须证明完整性和去重；缺用量或对不上时，立即 `stop_requested`，标记 unknown，不允许估计值 `usage_complete=true`。
- Provider 发送之前必须使用有期限、单用户/单 Run 绑定的 `TaskBudgetExecution` 做原子 reserve + dispatch，真实工具 Registry 在**副作用发生前**完成工具 allowlist/额度检测。离线 `t1_budget_gate.py`、提示词、聊天消息、Web 旁路代理或仅事后统计都不构成真门禁。
- 单次请求的 token 尚未从 Provider 回来，必须在发送前使用**保守可证明的请求上界**（例如 JSON payload UTF-8 bytes + 允许输出 tokens + 协议余量）预占完整上界，使任何一次回复后不能超出冻结额度；前置字节额度和 Provider max_tokens 均须有生效证据。无法证明则该请求拒绝，不回退到无预算通道。当前试验脚本采用 (2×canonical JSON bytes+8000) 的输入 token-equivalent 预占，**尚未证明与智谱 tokenizer 的严格上界关系**，因此这只能作为保守代理上界，不能宣传为经证明的全量 token 硬限。
- 新预算授权不可继承旧根；停止、超限、Session/进程中断后旧预算不可重新激活。重新执行需要独立新 Root 和明确准入。保留真实物理未知负债，不能用 `stop_requested` 当作远端取消/结算证明。

## 写入与证据准入

- 只准在该隔离树内使用 `read_file(snapshot=true)` → `edit_file(expected_snapshot_ref=...)` 对已存在目标进行原子 CAS。新文件需要经过工具 schema 确认的 create-only 路径；不存在则本批先使用 Git 已跟踪的固定 FX05 初稿，不能以 `/tmp/*.py` + `execute_command`、here-doc 或隐蔽替代姿势规避。
- 写前核 `Goal/Task claim`、权限、当前预算 phase/余额、Run/Session 绑定、快照 hash、目标目录；写后读真实字节、验证段落内容、SHA、一次性标注 attempt 身份。人工独立复核而不是执行者自称 PASS。
- 禁止将可变预算 ledger（运行态状态文件）混在受审 Git tree 中；另存于持久运行数据目录，候选只引用固定 receipt/hash/snapshot，避免预算 `request_stop` 导致候选 SHA 漂移。审查前冻结完整补丁集和 evidence；候选变化必须重新审查。
- 新样本默认只做 1 个 FX05 样本任务，不沿用旧 8 fixture + 2 repeats 的成果为合规证据。M1 单例通过后再决定扩到 N/F/R，不用追加样本美化成功率。

## 闸门与部署

1. **先证实真门禁已接到实际 GLM Provider/Registry dispatch 并完成超额/撤销 fail-closed 演练**。若当前 Web canary 默认 OFF 或固定 profile 不支持允许写入的真实预算，不得靠改预算文件或把开发会话的无限流量标为预算受控；要么在隔离服务实现并验证最小桥接，要么停在 HOLD。
2. LFL GLM-5.3 单一 writer 只修改隔离树；独立 Reviewer completed/PASS/P0=P1=0，候选 SHA/审查范围一致。
3. 原版完整 `bash scripts/ci_gate.sh --release` 真实 exit 0；再受审查 push 候选 branch，核远端精确 commit CI；保护本地 main 脏修改，按仓库流程隔离集成 main 并核最终 tree。
4. Mac 以现有 source_checkout 受管发布合同为准，wheel 仅在切换至 wheel_release 被独立批准时才是硬约束；需核 WebUI artifact / source SHA / 配置指纹 / desired-live-stable / PID / health / idle / barriers。`all` 之后 WeCom 单独受管 restart，确认四服务实际加载身份，失败按受管 rollback 并产生新 generation。

**根本裁决：保证实际能力，不为完成流程指标新增第二套框架。不能机械证明的预算维度标 unknown，且严格拒绝把不合格候选发布为合格生产版本。**

## 2026-11-13 真实执行的结果与仍缺资格

- Mac 现有权威 Provider registry 的 GLM 配置在生产 data 目录，不在隔离目录。首次隔离引擎仅继承旧 DeepSeek 合成注册表，但显示模型标签 glm/glm-5.3；已在进程内先加载 Mac 真实注册表并重新绑定模型路由，验证 provider=glm / model=glm-5.3 / HTTPS host=open.bigmodel.cn。不能把错误标签路由当 GLM 真值。
- 新预算根首次实测产生 1 个真实 Provider physical dispatch reservation，input_token-equivalent 预占 28,098、output_token 预占 6,000、payload 10,049 bytes；Provider ReadTimeout 120 秒，无有效 usage、工具 0，最终根 stop_requested、未知负债不退费。
- 第二个**独立新根**使用 GLM-5.3 的 low reasoning_effort，仍在 180 秒 ReadTimeout，无有效 usage、工具 0，预算根 stop_requested。两次 FX05 源文件 SHA 均保持 ad44484566051fad39f12ba070dfe95738677cc1118a31d7f4dfdb9b12a2a1ab；**未完成真实文稿修改**，不得将试验计为通过样本。
- 无密钥 GET/HEAD 连通性检查对 open.bigmodel.cn 返回 HTTP 401（说明 DNS/TLS/HTTP 通路可达，不证明模型推理可用）。出现两次真实 GLM 超时后不无限重试；后续须先取得有效 GLM 回应和可信 usage，再申请 M1 开发验收。
- 原代码相关 TaskBudget 契约定向回归 55 passed；新 M1 预算 reserve/stop/allowlist 四项测试 4 passed，ruff/pyright 通过。这些只证明本地模型尝试前的 CAS 和工具拒绝面，不是 T1 内容完成、F18 端到端或正式 R9 的证据。

## 2026-11-13 预算隔离传输复测与 FX05 实际产物

- 新增 `--smoke` 只发一条极小 GLM-5.3 请求，仍走真实 `FX05BudgetExecution` / `checked_provider_attempt` / I5-D 单请求 worker。直连 1.740s（17 input / 3 output）；显式 Surge loopback proxy `127.0.0.1:6152` 2.013s（17 input / 7 output）。两者都 HTTP 200、usage report=1、physical=1，结束后各自预算根 `stop_requested`。这排除了“GLM API 不可用”和“Surge 代理整体不可达”，但不单独证明之前超时的唯一根因。
- 将完整 FX05 放到同一个 I5-D 独占 worker、TLS 验证开启、直连（无系统代理发现）后成功完成三轮真实请求：3/3 HTTP 200、Provider 观测模型 `glm-5.3`、3 份 `request.usage`。合计 input=8,520（含 cache hit 7,360）、output=175、reasoning=25；实际工具 `read_file → edit_file → read_file` 均 success。原共享 HTTPX transport 路径与 I5-D worker 的差异包括连接/进程所有权、代理发现及 socket 生命周期；目前证据只说明隔离 worker 路径成功，不足以把旧 ReadTimeout 唯一归因于代理。
- `edit_file` 的 effect receipt：before SHA=`ad44484566051fad39f12ba070dfe95738677cc1118a31d7f4dfdb9b12a2a1ab`，expected/actual after SHA=`6ec241cd185f1c4145d26d4adb847b6bf055e7a813ad8adb12eb5bd3609e5129`，`matches_expected=true`。再次独立读取并与 Git 中原始字节比较：仅唯一日期 `2026-11-20` → `2026-11-27`，新旧均 418 bytes，`new_bytes == old_bytes.replace(old, new, 1)` 精确成立。
- 预算根 `m1fx05-bb5e0437cde64f3d907d0954e3eb26ae` 停止于 revision 21：physical=3/3、tool=3/8、输入 token-equivalent 预占 92,456/400,000、output 18,000/400,000、payload 34,228/2,097,152。物理 reservation 依 I2 仍保留 UNKNOWN（没有把 usage 回执误当远端物理结清）；精确真实用量以 3 条 EventStore `request.usage` 为准。预占输入等价值仍不是经 GLM tokenizer 证明的严格 token 上界。
- 由于冻结 `max_iterations=3` 恰好耗尽于第三次成功的 `read_file` 后，LoopResult 的 run reason 为 `max_iterations` 且 `run_incomplete=true`，未生成最终 assistant 自然语言答复。不能将其表述为完整 Loop 完成；但任务要求的实际文件副作用已由 effect receipt、第三次读取、独立 SHA/字节比较机械验收为 **FX05 artifact PASS**。该事实及事件日志引用固定记录于 `docs/receipts/M1-FX05-20261113.json`。
- M1 专项预算测试增至 6 passed，新增"无绑定预算的 Provider 请求 0 dispatch 即拒绝"和"缺少 usage 时保留 UNKNOWN reservation 并 fail-closed"两项负测；Ruff / Pyright 0 错。55 项原有 TaskBudget 定向回归仍需对最终冻结候选重跑。

## 2026-11-13 阶段1最小补修（v3，HEAD=db6a2546a 之上的未提交候选）

单一 writer glm/glm-5.3（session 59d664ee-98e2-4f7f-bf0b-79cdb910e980），零子代理、零并行 review；旧树 m1-t1-fx05-20261113 的在审结果与旧预算根全部只读保留，未 reset/rebase/清理。改动仅 2 个文件（`scripts/m1_fx05_budgeted_run.py` +221/-19 行有效、`tests/unit/test_m1_fx05_budgeted_run.py` +201 行），全部落在本隔离工作树，**未 commit，待主代理交叉核验**。

- **A（4 轮与预算重算）**：`ATTEMPTS 3→4`、`MAX_JSON_BYTES 55k→40k`、`MAX_OUTPUT_TOKENS 6k→3k`，新增命名常量 `INPUT_PROXY_CONST=8k`。每 attempt 输入代理 `2*40k+8k=88k`、输出 3k；4 attempts 最坏预占合计 `4*91k=364,000 ≤ 400,000` 总 token-equivalent 上限（输入单维 352k、输出 12k、payload 160k 均在 grant 内）。`settings.max_iterations=ATTEMPTS` 同步为 4，第三轮工具后仍留一整轮自然语言总结。不能只改 max_iterations 的要求由 payload/output/预占常量联动满足。
- **B（Provider usage 与 ledger 对账，FX05 专用，全局 I2 零改动）**：`FX05BudgetExecution` 新增 `_m1_envelopes/_m1_observed` 簿记、`record_observed_usage()`（同值重复幂等、异值标 conflict；cached input 记账不扣减）、`settle()` override。生产 `checked_provider_attempt` 的 `settle(complete=False)` 被拦截：当且仅当 usage 观察恰一次、无冲突、`actual ≤ 预占 allocations` 时 CAS 升级为 `usage_complete=True`，receipt_ref 绑定 provider attempt id 与 usage 摘要（如 `m1fx05-usage-dispatch-<hex>-attempt0-in1500-out40-cache300-bytes1000`）；actual 超预占、usage 冲突、usage 缺失一律保留 UNKNOWN 并 latch `request_stop`（固定 reason 常量，幂等），不退款、不放下一次物理请求。allocations 保持预占值不回落。
- **C（上界标注）**：所有预占公式继续标注 conservative token-equivalent proxy，不宣称 GLM tokenizer 数学上界；单请求 payload ≤40,000 bytes、max_tokens ≤3,000、物理 attempt ≤4，发送前 CAS reserve+mark_dispatched（v2 已有，保留），真实 usage 回来后按 B 对账；EventStore `request.usage` 与 receipt_ref 摘要双留痕，cached input 计入总 input。
- **D（负测矩阵，全部合成 fixture）**：`tests/unit/test_m1_fx05_budgeted_run.py` 6→11 个测试。新增：成功对账正测（receipt_ref 正则断言+不退款）、actual>precharge（UNKNOWN+stop+`usage_reports` 已+1 时仍拒下一次）、重复异值 usage conflict（UNKNOWN+stop）与 UNKNOWN 不可被 `complete=True` 事后升级+同参 replay 幂等、provider 超时（outcome=failure、UNKNOWN、`m1_previous_provider_usage_unknown` 挡下一次）、4 轮预占 ≤400k 算术断言。既有覆盖：unbound provider / unbound usage / 未授权工具 / persisted stop 阻断工具与 Provider / 预算天花板预拒（本文件）；stale CAS、interrupt recovery、重复执行不重复写入、parallel editor CAS 等在 `test_task_budget_*.py` 既有集（本次回归全过）。
- **E（真实命令与 exit code）**：主仓 `.venv`（Python 3.13.13；系统 python3=Xcode 3.9 无 StrEnum 不可用）：`py_compile` exit 0；`ruff check`（脚本+测试）exit 0 "All checks passed!"（修一处 SIM105→`contextlib.suppress`）；`pyright`（两文件）`0 errors, 0 warnings` exit 0（settle override 首版 10 错重构后清零）；M1 预算专用测试 `11 passed in 0.10s` exit 0；TaskBudget 相关回归 `pytest -k "task_budget or m1_fx05"` `346 passed, 4 skipped`（4 skip=既有环境受限 RED-12~15 mailbox ACL，与本次改动无关）。FX05 artifact 验收独立保留为上一节 receipt；本轮未再跑 GLM——若再跑必须全新 root（不复用 stop_requested 的 m1fx05-bb5e0437），run_incomplete 语义仍以新 receipt 为准。
- **F（入口契约与纪律）**：`scripts/m1_fx05_budgeted_run.py` 是隔离 CLI 实验入口，不是已集成 Web 入口（docstring 显式声明），不冒充生产 entrypoint。本轮零 push、零 main/R9/部署、零新 Reviewer 启动；候选未 commit，等主代理交叉核验后再按用户顺序进入冻结与独立审查。过程事件：ruff SIM105 一处、pyright Optional-narrowing/返回注解 10 处（均已修复并复跑通过）、无越界写。

## 2026-11-13 21:52 主代理交叉核验缺陷修复（v3.1）

主代理只读核验提出 5 项缺陷/要求，逐项处置（全部限于 scripts/tests/docs，src/llm_loop 生产源零改动）：

1. **恒真对账**：v3 settle 中 `payload_bytes <= payload_bytes` 确属实缺陷，已删除。对账改为读回 CAS store 的权威 reservation 记录：`member_id`/`run_generation` 归属精确匹配 + `allocations{input_tokens,output_tokens,payload_bytes}` 逐键 int>0 校验 + 本地 envelope 必须与权威 allocations 三元组精确相等（actual prepared bytes == ledger payload_bytes）；observed input/output 非负且 cached<=input。任一不符→UNKNOWN+新 stop reason `m1_reservation_ledger_mismatch` / `m1_observed_usage_invalid`。
2. **返回类型**：核实现状——磁盘 v3 的 override 与父类 `TaskBudgetExecution.settle`（dispatch.py:275）均为 `-> None`，无 dict 标注；本轮保持 `-> None` 并在 docstring 显式声明；全文件 grep 无 `type: ignore`/`# pyright`（exit 1 无命中），pyright 0 errors 非掩盖所得。
3. **两口径耐久回执**：新增 write-ahead sidecar `data/m1-budgeted-run/<root_id>.usage-receipts.jsonl`（schema `m1fx05-usage-receipt-v1`，每 reservation 恰一行终局记录）：绑定 reservation_id、member_id/run_generation、provider event ref（usage.id 透传）与 usage_sha256（canonical JSON 哈希），同记 reserved（=store allocations，预占口径不动）与 observed（provider 实测口径）双份数据 + verdict。settled 升级前必须先落盘回执；回执不可写（OSError）→UNKNOWN+`m1_usage_receipt_unwritable` fail-closed。保守预占仍是唯一硬拒绝账本；文档明确不宣称数学严格 token 上界。
4. **不复用旧产物**：原 FX05 目标（2026-11-27 修订版）只读保留。新增 `--target-path` CLI 参数与 `_refuse_existing_target()`：`--execute` 时目标已存在即拒绝（`m1_refuse_overwrite_prior_fx05_target`）；正式 4 轮复测须全新目标路径+全新合成输入快照+全新预算根（不复用 stop_requested 的 m1fx05-bb5e0437），所有历史 append-only。
5. **负测扩展**：11→18 个（全合成）。新增：envelope/ledger 漂移（UNKNOWN+ledger_mismatch 回执+stop）、归属篡改（monkeypatch 伪造 member_id→UNKNOWN+不退款+stop）、observed 无效（cached>input 与负 input 双例→observed_invalid）、同 CAS 快照 settle 重放幂等（revision 不变+回执单行）、stop 后 provider 与 tool 同拒（新 dispatch 与 assert_tool_allowed 双断言）、回执不可写 fail-closed、拒绝覆写既有目标（正反例）。
6. **验证回执**：`py_compile` exit 0；`ruff check`（脚本+测试）All checks passed；`pyright` 0 errors, 0 warnings（两文件）；M1 专项 `18 passed`；`pytest tests/unit -k budget` `568 passed, 4 skipped`（4 skip=既有环境受限 RED-12~15，与本次无关）。本轮未跑 GLM，未 commit/push/main/R9/部署，零新 Reviewer。

## 2026-11-13 22:15→23:30 父侧交叉审核修复 + 真实 GLM 闭环复测（v3.2）

父侧交叉审核指出两项必须修正（预算账本与真实 Provider 用量对齐、真实 transport attempt id 绑定），处置如下（仍仅 scripts/tests/docs，`src/llm_loop` 生产源零改动；全部检查统一主仓 `.venv/bin/python`=3.13.13——系统 python3 是 Xcode 3.9 无 `StrEnum`，conftest ImportError 属解释器事实，非代码回归）：

1. **真实用量改写预算账本（修复 #1）**：新增 `FX05BudgetExecution._m1_settle_with_actual_allocations()`，走既有 `TaskBudgetStore._mutate(budget_id, expected_revision, apply)` CAS 通道（签名已核 task_budget_store.py:398）：apply 内验证 reservation 归属（member_id/run_generation 精确匹配）、`phase==dispatched`、input/output/payload 三 int 且 ≤ 原 precharge、payload==prepared 投影，然后在**同一原子步**把 `allocations{input_tokens,output_tokens,payload_bytes}` 改写为实测值并落 `phase=settled/outcome=success/receipt_ref`。同证据重放=no-op（revision 不变）；异证据=TaskBudgetConflictError；超预占/归属不符=拒绝并保留 UNKNOWN+precharge（stop，不退款）。`settle()` 成功路径改为调用它；digest 绑定 pre-send envelope（settle 时经 ledger_ok 证明=权威行），settle 后重放重算一致实现幂等短路。`store.report().used_or_reserved` 因此反映真实 usage；**cached input 计入 prompt_tokens 不扣减、不重复相加**（单测断言 input==1500 而非 1200；真实回执 observed.cached_input≤input）。
2. **真实 Provider transport attempt id（修复 #2）**：`on_usage` 从 `self.transport_observer._active_transport.get().attempt.attempt_id` 读取真实 `ProviderTransportAttempt` id（实际格式 `pattempt:`+uuid4hex，铸造点 provider_settlement.py:393；engine 装配点 factory.py:1085-1088 已核）。无活动 attempt 或非 str → `m1_provider_attempt_id_unavailable` stop 并拒绝结算，**绝不用本地轮次序号冒充**。`receipt_ref=m1fx05u:<attempt_id>:<sha256(envelope+observed)[:16]>`，≤96 字符符合 `_identifier`。`record_observed_usage(attempt_id: str, ...)`。
3. **payload 口径（修复 #3 配套）**：恒真检查已于 v3.1 删除；本轮 `_PRE_SEND_PREPARED_FACTS` 把 payload HMAC/key_id/projected_bytes 随 envelope 捕获进 receipt（真实运行中 HMAC 实际存在，见回执）。
4. **目标守卫新语义**：`--execute` 下历史 `TARGET_PATH` 恒拒；新路径目标（read_file→edit_file CAS 需其先存在）必须 `--prepared-target-sha256` attestation 精确匹配（fixture 分账：受控 create-only 准备与被测工具动作分开）；缺失目标/无/错 attestation 全 fail-closed。

### 真实 GLM 闭环复测回执（2026-11-13 23:00，一次性，不再重跑）

- **命令**：`.venv/bin/python scripts/m1_fx05_budgeted_run.py --execute --prompt-file t1-sandbox/inputs/fx05-v3r2-prompt-20261113.md --target-path t1-sandbox/outputs/fx05-v3r2-fixture-20261113.md --prepared-target-sha256 845ae7e8…5399`；**进程 exit=3**。
- **exit 3 根因（已定位并修复，非账本缺陷）**：v3.2 首版 `_verify_ledger_alignment` 把 3 个 tool_invocations 预留也按物理预留要求 usage-receipt join（工具预留无 provider usage 可 join，本就由 dispatch-receipt 收口）→ 整体 `aligned=false` 退出码 3。已改为：仅物理预留（allocations 含 input_tokens）要求 m1fx05u join；工具预留要求 `receipt_ref==dispatch-receipt-<rid>`；单测 `test_ledger_alignment_classifies_tool_vs_physical_reservations` 覆盖混合根全对齐与物理缺回执行两态。按父侧指令未再真实重跑，本回执如实记录 exit 3 及根因。
- **运行主体事实**（root=`m1fx05-8b3741c3ffa4461cb4e8002918429e21` 新根，session=`f5b6bc77-ebdf-4db6-8eea-492f623d58f0`，generation=`5e8dbe260ec74fd1891034c8c6ff7d7c`）：terminal `run_incomplete=false`，rounds=4、tools=3（read_file→edit_file CAS→read_file）、physical_attempts=4、usage_reports=4——**4 次物理 attempt 恰好支撑 3 个工具轮+1 个总结轮，无需第 5 轮**；超限/无 usage/冲突立即 stop 由负测矩阵覆盖（exceeded/conflict/usage_missing/timeout）。
- **账本对账**：4 物理预留全部 settled/success 且逐条 `aligned=true`，receipt_ref=`m1fx05u:pattempt:<32hex>:<16hex>` 与 sidecar 行 attempt_id 一对一精确 join；allocations 已是实测值：input 3598/2432/2821/3305（合计 12,156）、output 132/38/130/32（合计 332）、payload 13873/9676/11098/12686（=prepared canonical bytes，合计 47,333≤4×40k）。`store.report().used_or_reserved`：`input_tokens=12156、output_tokens=332、payload_bytes=47333` 与 terminal 双向一致；cached（按 attempt 序 65b3→0ef8→74c5→292a 为 0/2368/2816/3264，合计 8448）计入 input 不扣减不重复相加。3 个工具预留 tool_invocations=1 各自 settled。
- **sidecar 回执**（v3.2 当时事实；该第二持久账本已于 v3.3 整体移除，文件降级为运行态 ignored data、不入 Git、不作为事实源）：`data/m1-budgeted-run/m1fx05-8b3741c3….usage-receipts.jsonl` 恰 4 行，schema `m1fx05-usage-receipt-v1`，reserved（precharge 口径）与 observed（实测口径）双留痕，payload_hmac+key_id=k1-aa7f7d16 实际存在，usage_sha256 各行独立。
- **产物字节核验**：目标 fixture 仅 "2026-11-06→2026-11-13" 单点替换（还原该串后 sha256=845ae7e8c2799cb731886384237da31289e73d9513707c9a7f729f469a715399 == 基线）；历史 `t1-sandbox/outputs/fx05-draft.md` sha256=6ec241cd185f…5129 未动；旧根 `m1fx05-bb5e0437…` 永不复用。
- **cached 顺序更正（v3.3，父侧复核后修正）**：按 attempt 时间序（65b3→0ef8→74c5→292a）cached_input_tokens 为 **0/2368/2816/3264**（合计 8448，全部包含于 input=12156，不扣减），此前文档所写 "3268/2368/2816/0" 顺序不准确；权威来源为 EventStore `provider.transport.settled` payload。

### M1/M2 覆盖矩阵与入口差距（如实）

| 维度 | M1 状态（本 worktree） | M2 缺口（未做，非已做） |
| --- | --- | --- |
| 预算 CAS 账本（reserve/dispatch/settle/rewrite） | 已实现+31 项单测+真实运行验证 | 生产 Web 会话未经此路径 |
| 真实 usage 对账（attempt id join） | 已实现：EventStore `provider.transport.opened`+`settled` 唯一事实源（opened 重建 reserved、settled 提供实测 usage；无 sidecar）+真实 GLM 4 attempts 验证+历史 root 端到端 digest 重算 4/4 匹配 | EventStore request.usage 与 webui 展示联动未接 |
| 入口 | 隔离 CLI `scripts/m1_fx05_budgeted_run.py`（docstring 显式非生产入口） | **Web 入口未接线：M2 blocker**，需在服务端把 budgeted execution 接入真实会话入口并过 Rule28 审查 |
| 负测矩阵 | 31 项全绿（含 fail-closed 全家族：join 缺失/重复/错 generation/usage 篡改/opened 缺失/envelope 分歧/CAS 冲突保持 UNKNOWN/receipt_ref 篡改/多余事件/未知 kind/event_store 缺失） | Web 层 end-to-end 负测未建 |
| 部署/canary | 无（按令禁止） | M2 决策 |

### 验证回执（v3.2 最终轮，全部 `.venv` 3.13）

`py_compile` exit 0；`ruff check`（脚本+测试）All checks passed（修 E741 六处、B039 一处）；`pyright` 两文件 0 errors, 0 warnings；M1 专项 `21 passed`；`pytest tests/unit -k budget`：571 passed, 4 skipped（570→571=+对账分类测试；4 skip=既有 RED-12~15）；`pytest tests/unit -k "m1 or budget"`：624 passed, 4 skipped。候选保持未 commit；零 push/main/R9/部署/canary/子代理。

## 2026-11-14 00:00→00:35 父侧四项冻结阻断修复（v3.3/v3.4，无真实 GLM）

按 23:55/23:58/00:01/00:10/00:12/00:17/00:20 系列指示实施，全部合成测试+历史 root 只读端到端证明，不再发真实 Provider 请求：

1. **删除第二持久账本**：`usage-receipts.jsonl` sidecar 语义整体移除（写入代码、`m1fx05-usage-receipt-v1` schema、`STOP_REASON_RECEIPT_UNWRITABLE` 全部删除）。Provider usage 唯一持久事实源 = 现有 EventStore。旧 sidecar 文件降级为运行态 ignored data，不入 Git、不作为事实源。
2. **settle 内 EventStore 双事件 join（fail-closed）**：`_m1_join_event_store_evidence` 按真实 `pattempt:<32hex>` attempt_id **恰好一条** join 两个事件——`provider.transport.settled`（usage 权威：provider=glm/model=glm-5.3/outcome=success/usage_observations=1/status 200 与观测逐项相等）与 `provider.transport.opened`（**reserved 的耐久事实源**：`payload.prepared.projected_bytes` + `controls.max_tokens`，重建 reserved={2·payload+8000, max_tokens, payload}）；generation 经 `provider.call.opened.origin_run_generation` 匹配 member。settle 时 rebuilt reserved 与本地 `execution._m1_envelopes` 三元**精确比对**，任何分歧（缺失/重复/错 generation/usage 篡改/属性不符/envelope 分歧）→ UNKNOWN + durable stop。on_usage 的 `provider_event_ref` 不再误读 `usage["id"]`，恒为空串；event_id 单独记录绝不冒充。
3. **CAS 是唯一结算提交点**：一次 `_mutate(expected_revision)` 原子改写 allocations+phase=settled+receipt_ref；CAS 冲突/拒绝 → ledger 保持 precharge 的 UNKNOWN（`m1_settlement_cas_conflict`），无任何声称 settled 的观察回执。新 receipt_ref = `m1fx05ev:<event_id>:<sha256(canonical)[:16]>`，canonical = `{attempt_id, provider_event_ref:"", observed, reserved}`（reserved 用 opened 重建值）。**不改共享 store schema**（reservation 键集严格白名单拒收 `reserved_precharge` 是实测事实，按最小范围回退为 FX05 局部 envelope + 耐久 opened 事件双源）。
4. **verifier 按 reservation.kind 分类且无 legacy 豁免**：`physical_attempts` 恰好 join 一条 settled+一条 opened（attempt_id 一对一、`pattempt:[0-9a-f]{32}` 强制、generation/usage/属性全核、多余 unjoined 事件失败），**legacy `m1fx05u:`（4 段，attempt id 自带冒号）与新 `m1fx05ev:`（3 段）同样从耐久事件重算 canonical digest 并精确比对第三段**——不存在 digest_ok=True 跳过。`tool_invocations` 只核 `dispatch-receipt-<rid>`；未知 kind fail-closed；UNKNOWN 行核 dispatch-receipt 收口；event_store 缺失 → `unavailable` 且物理行失败（不虚称对账完成）。
5. **历史 root 端到端复验（只读，不改写）**：4 条 legacy digest16 全部由 opened+settled 重算**精确匹配**（41fdfd4b…/5223eb28…/182f8663…/bfa128cf… 4/4 True），`_verify_ledger_alignment` 对历史 root 跑通：7 reservations 全对齐（4 physical joined、3 tool not_required、无 extra 事件、aligned=true）。**历史 ledger 未改写、未换前缀**。
6. **归档**：`docs/receipts/M1-FX05-v3r2-20261113.json` 如实记录 `ledger_receipt_ref_format=legacy_m1fx05u`、`recomputed_digest_matches=true`、每 attempt 的 opened/settled 双 event_id、usage_sha256（canonical `{event_id,attempt_id,provider_id,model_id,usage}`）、observed/reserved、字节证明；不覆盖旧 receipt。新输入 prompt 与新输出 fixture 精确加入候选（仅对单文件 `git add -f`，无批量 force-add；data/ 预算/锁/运行态不入 Git）。
7. **EventStore 路径只读确认**：`event_logs_dir_override=false`，真实路径 `<worktree>/data/m1-budgeted-run/event_logs`（`f5b6bc77-….jsonl`，4 settled + 4 transport.opened + 4 call.opened 绑定 generation=5e8dbe26…）确在隔离树；main() 打印 `event_store_path` 事实行。

### v3.3/v3.4 验证回执（全部 `.venv` 3.13，2026-11-14 00:3x）

`py_compile` exit 0；`ruff check` All checks passed；`pyright` 两文件 0 errors, 0 warnings；M1 专项 **31 passed**（21→31：+join 缺失/重复/错 generation/usage 篡改/opened 分歧/CAS 冲突保持 UNKNOWN/receipt_ref 篡改/allocations 篡改/多余事件/未知 kind/event_store 缺失 fail-closed，成功路径与 replay 注入合成 EventStore）。**历史 root verifier 端到端 aligned=true**。候选未 commit；零真实 GLM/Reviewer/R9/push/main/重启/部署/子代理。旧根永不复用。

## 2026-11-14 00:34 父侧 FakeStore 负向补修（v3.5，最终冻结轮）

父侧用 FakeStore 直调 `_verify_ledger_alignment` 实测三例曾返回 aligned=true，全部修复并写回归（M1 专项 31→**35 passed**）：

1. **未知 kind 任何 phase fail-closed**：kind 门禁移到 phase 分支之前——`kind ∉ {physical_attempts, tool_invocations}` 时无论 settled/unknown 一律 `aligned=false`（`join_status=unknown_kind`），不再被"UNKNOWN 行只需回执前缀"路径吞掉（回归 `test_verifier_fail_closed_on_forged_rows` 案例一）。
2. **工具 allowlist 单一真值**：新增模块常量 `FX05_ALLOWED_TOOLS = frozenset({read_file, edit_file, get_tool_schema})`，grant 构造与 verifier 共用（无双真值漂移）；settled tool 行除回执精确匹配外还要求 `tool_id ∈ FX05_ALLOWED_TOOLS`（`exec_command` 即使回执精确也 fail，`join_status=tool_not_allowed`；案例二）。
3. **UNKNOWN 回执精确匹配**：UNKNOWN 行（tool 与 physical 同等）要求 `receipt_ref == dispatch-receipt-<rid>` **精确相等**，删除 `startswith`（`dispatch-receipt-unrelated` fail；案例三）。
4. **join 链一致性**：settle join 与 verifier 均要求 `transport.opened.call_id == settled.call_id`（跨 call 拼接 fail，回归 `test_settle_and_verifier_reject_cross_call_opened_splice`）；verifier 加 `0 ≤ cached_input_tokens ≤ input_tokens` 与 `allocations input/output ≤ opened 重建 precharge` 两项（回归 `test_verifier_rejects_cached_out_of_bounds_and_over_precharge`——cached 越界在 settle join 即 `cached_input_unqualified` 拒绝）。
5. **cached=None 规范化**：provider usage 流缺 `cached_tokens` 时，settle 的 digest 输入用**权威 EventStore 事件**的 `cached_input_tokens` 规范化（不本地伪造、不留 null），verifier 从耐久事件重算同一 digest 精确一致（回归 `test_settle_normalizes_missing_cached_from_event_store`，含 receipt_ref 全量重算断言 + verifier aligned）。

### v3.5 验证回执（全部 `.venv` 3.13，2026-11-14 00:4x）

`py_compile` exit 0；`ruff check` All checks passed；`pyright` 两文件 0 errors, 0 warnings；M1 专项 **36 passed**（31→36：+UNKNOWN 行工具 allowlist 负测：+上述四回归）；TaskBudget 回归 **335 passed, 4 skipped**；`pytest tests/unit -k "m1 or budget"`：**639 passed, 4 skipped**。历史 ledger/旧 receipt 未动；无 sidecar/新 schema/真实 GLM/Reviewer/R9/push/main/重启。

## 2026-11-14 06:45 父侧 P1 复现反例修复（CRLF/replace_all 2 MiB gate；F18 跨实例守卫）

父侧在当前未冻结 T1 源码、纯 TemporaryDirectory 实测：CRLF 目标 `(b'A\r\nX')*100000`（400k bytes）配 LF 形式 `old_string='A\nX'`、`new_string='A\n'+'Y'*30`、`replace_all=True` 时，旧 gate 用 `raw.count(old_b)=0` 只预估单次 +29B 增长放行；而 FileService.edit 在 LF-normalized 文本上实际匹配 100,000 次并全文恢复 CRLF，真实结果 3,300,000 bytes > 2,097,152——`OVERSIZE_CRLF_REPLACE_ALL_ENTERED_TOOL_SCOPE=True`。修复采用父侧建议的**精确上界**方案（保留 replace_all 语义，与既有 `t1_edit_result_exceeds_size_bound` 测试语义兼容）：`_t1_assert_edit_size_bound` 改为与 FileService.edit 同构计算——occurrences 计数在 LF-normalized 文本（replace_all 用全量计数、单次编辑保守 >=1 下限；`NoMatch/MultipleMatches` 由工具层拒绝，growth 永不缩小），CRLF 主导时按"存活换行数上界（原文 + 注入）×1 字节"计入全文 CRLF 恢复膨胀，非 UTF-8 目标直接拒绝（FileService 反正无法解码）。父侧反例数值复核：normalized 300,000 + growth 2,900,000 + CRLF 上界 ≈3.6M > 2 MiB → 预写拒绝，零字节写入。

F18 补核（父侧提醒"同 execution 本地 latch 有效，勿误报同 Run fail-open"）：新增跨实例守卫 `_t1_assert_no_open_liability`——仅在本实例**首次 reserve 前**执行一次，扫描 durable ledger 中非终态预留（终态=settled/aborted_before_dispatch），存在 UNKNOWN/dispatched 负债即拒绝 `t1_root_has_unsettled_liability`。作用域精确限定：同 Run 内工具失败（I2 语义允许参数层 fail-closed 后继续）不受影响；场景是"前实例的 durable stop 写 CAS 失败/未落盘，root 仍 active 且带 UNKNOWN 负债"时，新进程/新实例重绑同 root 的第一笔消费被账本本身拒绝。持久 stop 成功路径（budget_not_active）与同实例 latch 各有既有测试覆盖，不重复计数。

新增 4 项负测（`test_parent_p1_*`/`test_parent_f18_*`）：① 父侧反例精确复现——replace_all CRLF 编辑预写拒绝 + 文件字节不变 + FileService dry_run 交叉验证真实结果恰为 3,300,000；② 同 CRLF 目标单次编辑（无 replace_all）同样被 normalized 计数上界拒绝（旧代码此处只算 +29B 会放行）；③ 正向控制——小目标唯一锚定 CRLF 编辑过 gate、真实 FileService 应用后实际字节 ≤2 MiB 且 CRLF 保留；④ F18——工具体内失败留 UNKNOWN 负债、root 仍 active，重绑 plan 的新实例首笔 read_file reserve 被 `t1_root_has_unsettled_liability` 拒绝。

验证（全 `.venv` 3.13）：T1 专项 36 passed（32→36）；M1 专项 36 passed；`-k "canary or t1 or budget"` 722 passed, 4 skipped（718→722）；Ruff（2 文件）All checks passed；Pyright 0 errors, 0 warnings。M1 index 不变（write-tree=59d73bfb…，六文件 staged 原样）；本轮增量全部 unstaged。零真实 GLM / git commit / push / Reviewer / R9 / 重启。

## 2026-11-14 07:0x 父侧 2MiB 上界算法复核：同构化收口（P1-2）+ snapshot_ref 权威化

父侧 06:59 复核指出估算式上界（raw 字节计数/per-occurrence 增长/自造 CRLF 判定）不是安全硬上界，并给出两条新反例路径。本轮把 P1 修复推进为**与生产 FileService.edit 完全同构**的纯内存预检，并按父侧指示权威化 snapshot_ref 提取：

1. **`_t1_assert_edit_size_bound` 同构重写**：不再做任何"估算"。直接 import 生产 `llm_loop.workspace.file_service.detect_line_ending/normalize_lf`（非再推导），在内存中执行与 FileService.edit 逐步相同的算法：UTF-8 解码（BOM 剥离同源）→ 三方 normalize_lf → normalized 文本计数 occurrences → 与 FileService 一致性预检（occurrences==0 拒 `t1_edit_no_match_preview`；occurrences>1 且非 replace_all 拒 `t1_edit_multiple_matches_preview`——这两类编辑工具层本就会失败，fail-closed 预拒与 dry_run 预检口径一致）→ 同一 `str.replace` → detect_line_ending 全文行尾恢复 → 精确 UTF-8 编码长度与 2MiB 比较。空 old_string 的字符间插入放大（len+1 次）、CRLF 主导判定、LF 注入恢复膨胀等全部由同构性自然覆盖，不存在第二套可漂移的判定逻辑。父侧反例（LF 形式 old_string 在 CRLF 目标 raw 中 0 次但 normalized 数万次 + replace_all）与大量 LF new_string 恢复膨胀均被精确覆盖。
2. **`note_t1_read_result` 权威化**：武装 gate 的 snapshot_ref 不再从结果文本正则提取（`_SNAPSHOT_REF_LINE` 已删除）。registry.py 调用处改为传递 SUCCESS 结果的 `ToolResult.artifact_facts`，profile 侧取 `artifact_facts[0]["artifact_ref"]`（tools/builtin/read_file.py 的物理快照权威 ref）。缺 facts/facts 无合法 `artifact://v1/` ref/参数非目标路径 → 不武装（fail-closed，下一次 edit 以 `t1_edit_without_armed_read` 拒绝）。
3. **测试对齐**：8 处武装调用迁移为 facts 形式；3 处旧测试编辑参数改为真实匹配磁盘内容（同构 gate 要求 old_string 真实匹配——gate 单测不执行工具、磁盘内容不变，这是语义收紧的正确结果）；`test_parent_p1_crlf_single_edit_*` 断言迁移为 MultipleMatches 预拒（同构语义）。新增父侧指定 2 负测：`test_t1_edit_size_bound_crlf_cross_line_replace_all`（60k 行 CRLF 目标 + LF 形式 old + replace_all：gate 拒绝、字节不变、FileService dry_run 交叉验证真实结果 >2MiB；并附单次同型编辑 MultipleMatches 预拒）与 `test_t1_edit_size_bound_lf_heavy_new_string_under_crlf_restore`（CRLF 主导 1.1MiB 目标 + 唯一锚点 + 100k LF new_string：恢复膨胀后 >2MiB 预写拒绝、字节不变、dry_run 交叉验证）。

验证（全 `.venv` 3.13）：T1 专项 **38 passed**（36→38）；M1 专项 36 passed；Ruff（profile+测试+registry）All checks passed；Pyright 三文件 0 errors, 0 warnings；综合回归结果见本轮汇报。M1 index 不变（write-tree=59d73bfb…，六文件 staged 原样）；本轮增量全部 unstaged。零真实 GLM / git commit / push / Reviewer / R9 / 重启。

## 2026-11-14 07:11 父侧最终收口批次：测试口径区分 + 真实 HTTP route 测试

1. **口径修正**：`test_t1_web_route_e2e_synthetic_provider_stream` 改名
   `test_t1_engine_scope_e2e_synthetic_provider_stream`，docstring 显式披露其范围=
   生产 `bind_web_canary(T1)` → 真实 `engine.run_stream` → 真实 LLMClient，**不含**
   HTTP 路由层/BackgroundRunner 派发。
2. **新增真实 route 测试**（复用 `test_task_budget_web_cutover.py` 的 TestClient+runner
   spy 模板，不新造框架）：`test_t1_real_web_stream_passes_pinned_plan_to_background_runner`
   ——真实 `build_app(engine=...)` + `TestClient` POST `/api/v1/chat/stream`，断言
   `BackgroundRunner.start` 收到 `signed_web_canary`（T1 plan 身份核验）且 sync 路由
   409；`test_t1_web_stream_route_denies_unqualified_requests`（4 参数组）——未认证
   403 canary gate / 错 model 403 / queue_id 409 queue-claim / attachments 400
   attachment-ownership（后两者为早于 canary gate 的既有 fail-closed 层，如实断言），
   共同断言零 runner 派发、零预算分配。session 用 `engine.session.create()` 真注册 id
   （字面 id 会先 404 session_not_found——这也是一处诚实边界）。全部合成，零真实 GLM。
3. 验证（全 `.venv` 3.13，真实 exit）：T1 专项 **43 passed**（38→43）；M1 专项 36
   passed；`-k "canary or t1 or budget"` **729 passed, 4 skipped** exit0；Ruff（M2
   全部文件）All checks passed；Pyright 8 文件 0 errors；py_compile 0。M1 index 不变
   （write-tree=59d73bfb…）；M2 增量仍全部 unstaged/untracked；新增独立 M2 冻结正文
   `docs/design/M2-T1-WEB-CUTOVER-FREEZE-20261114.md` 与执行回执
   `docs/receipts/M2-T1-WEB-CUTOVER-20261114.json`。零真实 GLM / commit / push /
   Reviewer / R9 / 重启 / 部署。
