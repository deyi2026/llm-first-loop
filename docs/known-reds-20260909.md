# 已知红清单（Known Reds Registry）

维护日期：2026-10-13 ｜ 维护约定：本清单是「测试分层」防复发机制的一部分（见 `docs/subsystem-disposition-20260909.md` §4）。
预存在红不是放任，而是显式登记的现实约束：每项必须走「修复 或 显式接受」二选一，禁止用扩基线的方式让红卫兵变绿。

各节结论仅适用于其注明的候选、时间和执行环境。历史基线「残留 = 0」不代表当前全量测试全绿；外部报告中的失败也须在当前环境复核后再归因。Skipped 表示未验证，不是部署资格或安全门禁通过。

## 1. origin/main 基线预存红（8 项，2026-09-09 复核）

来源：origin/main 全量跑（存档 `/tmp/lfl-main-baseline-reds.txt`，已迁入本文件）。
复核结论（fix/restart-useful-continuity 线，2026-09-09 定向重跑）：**7 项转绿（exit=0），1 项退役，残留 = 0**。

| # | 测试 | 状态（2026-09-09） |
|---|---|---|
| 1 | tests/unit/test_err1210_session_isolation.py::TestTwoSessionInterleaving::test_interleaved_a1_to_a6 | 已退役：类在当前树不存在；宿主文件现役 2 测试全绿 |
| 2 | tests/unit/test_evidence_phase7_gate.py::test_r0_12_non_target_guardrails_and_no_provider_policy | 定向重跑绿 |
| 3 | tests/unit/test_evidence_r2_runner.py::test_r2_b0_is_observational_and_dry_demonstrates_repeat | 定向重跑绿 |
| 4 | tests/unit/test_evidence_r2_runner.py::test_r2_e1_reusable_dry_uses_hydration_without_source_repeat | 定向重跑绿 |
| 5 | tests/unit/test_evidence_r2_runner.py::test_r2_f6_dry_refreshes_once_then_hydrates_new_evidence | 定向重跑绿 |
| 6 | tests/unit/test_evidence_r2_runner.py::test_r2_frozen_scorer_passes_dry_contract_shape | 定向重跑绿 |
| 7 | tests/unit/test_evidence_r2_runner.py::test_r2_invalid_evidence_ref_is_tool_failure_not_infra | 定向重跑绿 |
| 8 | tests/unit/test_s2_fixture.py::test_s2_matrix_is_balanced_and_secondary_sample_stratified | 定向重跑绿 |

## 2. HEAD 预存红（4 项，working_set 投影）

来源：增量2 终验（r4 全量 + 七片并行双口径一致，2026-09-09 17:31，4816 passed / 4 failed / 23 skipped）。
定性：测试文件 `tests/unit/test_tool_working_set_projection.py` 于 2026-09-07 落盘于本地 fix 线（不在 origin/main）；
其被测实现 `src/llm_loop/.../episode_history.py` 未被增量2 diff 触碰，与增量2 无因果。**处置待定：修复 或 显式接受，二选一。**

| # | 测试 | 定性 |
|---|---|---|
| 1 | tests/unit/test_tool_working_set_projection.py::test_working_set_receipt_compacts_only_older_exposed_group | HEAD 预存红 |
| 2 | tests/unit/test_tool_working_set_projection.py::test_working_set_stats_report_only_mechanical_projection_facts | HEAD 预存红 |
| 3 | tests/unit/test_tool_working_set_projection.py::test_working_set_stats_expose_incomplete_batch_without_folding | HEAD 预存红 |
| 4 | tests/unit/test_tool_working_set_projection.py::test_working_set_receipt_exposes_mechanical_origin_not_task_judgment | HEAD 预存红 |

## 3. 2026-10-13 macOS 环境差异复核（R1–R3）

复核者：本轮维护执行者；处置负责人：仓库维护者；复核环境：LFL MCP Console、macOS 26.5.1 arm64、Python 3.13.13。
候选基线：`main@3af8213fa6aea5acc2cf4e632e22a6c31a31cca5` 加当时暂存的 Phase4 源码/测试改动，在隔离 worktree 固定验证。
源 index tree：`0ee9001cfeb9a0a9d50a19d9bbaf9513bc9eb6bb`；继承补丁 SHA-256：`53eb8f2a4b76dd9946c00efe8b1d4c446a7a625b4cec7b62698c0581c238f4d2`。
本节不为其他暂存改动背书，也不产生发布/重启资格。

定向基线命令（默认排除 real_llm）：

```bash
python -m pytest tests/phase4/test_m2_inflight_interrupt.py::test_d_gate_conservative_matrix tests/unit/test_assurance_p1_process_reviewer.py tests/unit/test_task_budget_operator_mailbox.py tests/unit/test_static_diagnostic_gate.py tests/integration/test_browser_semantic_guard_e2e.py tests/integration/test_browser_dispatch_settle_e2e.py -q --tb=short --junitxml=data/r123-baseline.xml
```

执行时使用项目 `.venv`，工作目录为该隔离候选。结果：**44 passed / 5 errors，exit=1**。原始 JUnit 位于候选 `data/r123-baseline.xml`，SHA-256：`5081efdafaed55a54c181d0a18d8d8819db11b1038b322e5f8c868679724cab0`；它是本地验收证据，不是公开能力分数。

| 复核面 | 当前结果 | 归因与处置 |
|---|---|---|
| `test_d_gate_conservative_matrix` | 1 passed | 当前候选已先构造 engine、后注册纯 sleep 工具；外部报告中的 UnboundLocalError 在此候选未复现。保留该回归用例，不推断历史代码闸是否执行 |
| `test_assurance_p1_process_reviewer.py` | 10 passed | 当前环境真实 sandbox-exec 用例通过；`(version 1) (allow default)` + true 探针 exit=0。外部报告的沙箱失败不应泛化为 macOS 全局不可用，不增加 skip 或放宽安全断言 |
| `test_task_budget_operator_mailbox.py` | 12 passed | 当前环境 chmod 0o2750 后观测值仍为 0o2750；外部报告的 setgid 失败未复现。单 UID 单测仍不替代真实多 UID 部署资格 |
| `test_static_diagnostic_gate.py` | 17 passed | 当前候选缓存不可写负例及其他诊断门测试通过；不登记为当前已确认源码缺陷 |
| `test_browser_dispatch_settle_e2e.py` | 4 passed | 当前环境使用可发现的浏览器完成真实 E2E；该结果只覆盖此文件 |
| `test_browser_semantic_guard_e2e.py` | 5 setup errors | Playwright 返回的默认缓存 executable_path 对应文件不存在；原 fixture 在 Popen 前未检查文件。按文件已声明的可选浏览器契约补存在性检查，缺失时准确 skipped；既有 CDP 未就绪分支也会 skipped，均表示未验证，不代表浏览器资格通过 |

语义守卫的 5 个错误节点：

- `test_e1_guard_pass_exempts_version_mismatch`
- `test_e2_neighborhood_change_is_rejected_without_execution`
- `test_e3_overlay_occlusion_is_rejected`
- `test_e4_detached_node_is_rejected`
- `test_e5_password_value_never_persists_in_plaintext`

复核条件：候选源码、Python、浏览器路径/缓存、执行宿主或权限改变时重跑受影响文件。浏览器功能资格验收必须在已安装浏览器的指定环境执行，并核实相关用例实际运行；缺少依赖或全部 skipped 应记为前置条件不足，不能声称资格通过。没有本轮 CI 运行证据时，不宣称「Ubuntu CI 全绿」。

### 全量门禁补充观察：保守矩阵时序竞争

本轮第一次 `scripts/ci_gate.sh` 的并行全量：**1 failed / 8747 passed / 146 skipped**；失败节点为 `tests/phase4/test_m2_inflight_interrupt.py::test_d_gate_conservative_matrix`，在副作用 settle 后期望 gate=True，实际 False。该文件随后按既有 D-B2-09 流程串行复核 **6 passed**，ci_gate 最终 exit=0；这不等于并行全量零失败，也不能据此宣称已确定根因。

处置：登记观察并修复测试的生命周期前提。原 fixture 只用固定 5 秒 sleep 保活，未确认工具进入在途就 enqueue，存在与前置队列消费或 run 结束竞争的窗口。改为 entered/release 事件同步，确认工具进入在途后执行原断言，finally 释放工具，并恢复临时修改的 run-generation context。全部保守矩阵断言保留；不增加永久 flaky 豁免、不修改生产门禁或历史基线。最终结果另见本轮验证回执。

---

## 10. Terminal-Bench v0 基线归因结果（2026-10-23，P0 收口）

> 关联：`docs/EVAL-PLAN-LFL-20261023.md` §15 ｜ 复算：`python3 eval/rules/attribute.py --run-dir eval/results/baseline_v0_terminus2_glm53_full/2026-10-14__20-23-44 --log eval/logs/baseline_v0_full.log`

**基线定案：不可用基线（按 D6，环境类失败占失败比 72.2% > 30% 阈值）。禁止进入任何能力比较。**

### 10.1 环境/供应商侧红（52 例，原 `unknown_agent_error` 兜底标签）

| # | 红项 | n | 根因 | 归属 | 状态 | 处置 |
|---|---|---|---|---|---|---|
| R-ENV-01 | Docker `compose build` 失败 | 27 | 缺 `T_BENCH_*` 环境变量注入（复现报 `services.client.container_name '' does not match pattern`）；补齐后 build 成功 | LFL harness 装配 | **红** | 重跑时用 `tb` 正常入口并补齐环境变量；已实测 build 可成功 |
| R-ENV-02 | `[Errno 24] Too many open files` | 16 | 宿主 `ulimit -n` = 256（macOS 默认），低于 Docker Desktop 并发需求 | 宿主环境 | **红** | 重跑前置 `ulimit -n 10240`（**尚未实测验证**） |
| R-SUP-01 | 模型 API 5xx | 9 | `RetryError`→`InternalServerError`（日志 **30** 处，其中仅 14 处带 task_id）；该 9 题 `total_input_tokens`/`total_output_tokens` 全为 **null** | 供应商侧 | **黄**（**残差归因**：判据为"既无 Docker build 失败行、也无 Errno24 行，且 LLM 交互阶段出现 5xx 错误块"，**非逐任务确定性判据**，证据等级弱于 R-ENV-01/02） | 需重试/退避；本轮不计为 LFL 能力问题。**剔除全部 9 例后环境侧仍为 43/72 = 59.7% > 30% → 不可用基线定案不变** |

### 10.2 口径类红（数据解读陷阱，非运行时故障）

| # | 红项 | 状态 | 说明 |
|---|---|---|---|
| R-DATA-01 | `failure_mode` 对已解决任务也被填充 | **红** | 7 例 resolved 中 3 例 `agent_timeout`、4 例 `unset`。失败分布**必须**以 `is_resolved` 为准；用 `failure_mode` 分布冒充失败分布的统计一律错 |
| R-DATA-02 | 题面 sha256 未记录 | **红** | 原运行无 hash → 不满足 D4/R4 版本锁；跨时间重跑不可严格对齐。重跑时须对每题 `problem_statement`+`test_patch` 记 sha256 |
| R-DATA-03 | token 字段大面积缺失 | **红** | `total_input_tokens` 三分：**nonzero 18 / zero 9 / null 52**（`total_output_tokens` 相同）→ D8 成本必报在此基线**不可满足**；引用该基线必须标"成本不可用"，**不得把 null 当 0、也不得把 0 当零成本** |
| R-DATA-04 | `path-tracing` 无判定 | **红** | harness 阶段失败（归 R-ENV-02）故未写入 `results.json`；已归因非留空，但**仍未产生判定**，重跑须纳入 |

### 10.3 agent 侧红（可比集内 20 例未解决，可归 LFL）

| 失败模式 | n | 归属 | 状态 |
|---|---|---|---|
| `test_timeout` | 9 | harness 判分/测试执行侧 | **红**（P1 排查） |
| `parse_error` | 5 | harness 判分解析侧（其中 4 例 `total_input_tokens`=0，测试实际未运行） | **红**（P1 排查） |
| `unset` | 4 | 无明确失败原因，判分未产出 | **红**（P1 排查） |
| `agent_timeout` | 2 | agent 执行侧（360s 上限） | **红**（P1 排查） |

> 口径提示：并列报 ①原口径 7/79 = 8.86%（Wilson 95% CI 4.4%–17.2%）②归因后 agent 可比集 7/27 = 25.93%（Wilson 95% CI 13.2%–44.7%，n=27，仅方向性）。**禁止只报其一。**


---

## 11. RULE-AI-28 全量测试准入不可达（2026-10-23，P1 期间发现）

> 关联：`docs/EVAL-PLAN-LFL-20261023.md` §5-P1 ｜ 复算：`review_admission(action=start, kind=full_test, ...)`

### 11.1 现象

对 CI 门禁命令发起 RULE-AI-28 全量测试准入，连续 4 次被拒：

| # | 尝试的 command | 拒绝原因 |
|---|---|---|
| 1 | `uv run --no-sync python -m pytest tests/ -q -m "not real_llm and not serial_signal"` | `review_kind_command_mismatch` |
| 2 | `... -m pytest tests/ -q`（无 `-m`） | `review_kind_command_mismatch` |
| 3 | `... -m pytest tests/ -q -m ...` | `review_kind_command_mismatch` |
| 4 | `uv run --no-sync python -m pytest`（不带路径选择器） | `review_artifact_exceeds_192kb: material=1016873B cap=192000B` |

> **2026-10-23 已处置（方案 B，人工审批）**：用户 2026-10-23 18:04 明确授权"把上限修改了"，
> 演进提案 `EVO-20261023-fc5c34b9`。上限 192KB → 2.5M 字符，错误码改名
> `review_artifact_exceeds_cap`，并按 RULE-AI-35 做了双侧实测。详见 §11.5。

### 11.2 根因（已读源码确认，非推测）

- **第 1-3 次**：`src/llm_loop/tools/review_host_admission.py` 的 `classify_host_shell` 逐 shell 段判定；带 `tests/` 前缀、带 `-m <选择器>`、带 `::` 的 pytest 调用一律视为**窄化选择器** → 返回 `None`（非 full_test）。故**只有不带路径与选择器的全量调用**才被识别为 `full_test`。
- **第 4 次**：准入材料 = `committed_delta` + `uncommitted_delta` + 未跟踪文件全文，静态上限 `_REVIEWER_STATIC_MATERIAL_CAP_BYTES = 192_000`。本分支相对 `main`（merge-base `3573875`）有 **15216 行增量**，其中 6 个 `evals/retrieval_ab/*20261023*.json` 消融存档各约 89KB，合计约 530KB → 材料达 **1016873B**。
- 该 6 个文件是**本会话之前已提交**的他人工作（2026-10-23 04:25-06:16，提交 `a2fc16c7b` 等），**不是本次产物**。`_RUNTIME_OUTPUT_EXCLUDES` 仅含 `reports/`，故它们**不在**可排除范围；`committed` 内容不可人为剥离。

### 11.3 处置与影响

- **未绕过该门禁**：未执行任何规避手段（未 stash、未改 base、未拆分提交、未删他人文件）。
- **影响范围**：仅影响"全量测试"这一特定动作的 RULE-AI-28 准入。
- **红数对账不因此受阻**：CI 门禁命令（带 `-m` 选择器）本身被分类器**明确豁免**，属窄化运行，可直接执行并对账红数。
- **登记为红**：需人工决定如何处置 `evals/retrieval_ab/` 的 6 个大体积存档（拆分/压缩/移出仓库/调整容量上限），属**授权边界事项**，不由本会话自行决定。

### 11.4 处置建议（供人工决策）

| 方案 | 效果 | 代价 |
|---|---|---|
| A. 把 6 个消融存档压缩（gzip + 只留摘要） | 材料降到 192KB 以下，恢复全量测试准入 | 需改他人已提交产物 |
| B. 提高 `_REVIEWER_STATIC_MATERIAL_CAP_BYTES` | 一次性解决同类问题 | 属**安全/容量边界**，需人工审批与演进提案，不自行放宽 |
| C. 拆分为多轮完整审查 | 机制注释明确支持 | 需多次审查，成本高 |
| D. 维持现状 | 全量测试准入持续不可达 | 门禁实质失效 |

### 11.5 处置结果（2026-10-23，方案 B 已执行）

**人工审批**：用户 2026-10-23 18:04 指令"本分支 committed delta 1.55MB > 192KB 上限，把上限修改了"。
演进提案 `EVO-20261023-fc5c34b9`（按该授权提交并执行）。

**改动是三处同口径的，缺一则门禁行为不变**（实测发现：只抬静态常量是死代码）：

1. **静态上限** 192,000 → 2,500,000（单位为**字符**，与 child 侧 wire 检查
   `sum(dict_wire_chars(m)) <= budget` 一致；原实现用字节比字符预算，单位混用）。
2. **错误码** `review_artifact_exceeds_192kb` → `review_artifact_exceeds_cap`（名字带数字会随数字变化而撒谎）。
3. **动态闸 token 口径**：registry `chars_per_token=0.6` 是中文混合标定（1.676 tok/char），
   对 88% ASCII 的代码/JSON diff **高估约 4.4 倍**，使预检对任何真实代码产物都不可能满足。
   改为按材料实际字符构成估 token 成本，且**预检与 child 用同一个函数**
   （`llm_loop.subagent.runner._wire_chars_per_token`），否则会"预检放行、child 仍拒"
   （child 是空工具子代理，超预算时**拒绝**而非截断）。

**标定用真实 provider 数据**（GLM-5.3 `usage.prompt_tokens`，非估算）：
材料 1,935,808 字符 → **762,018 token**（2.540 字符/token）；ASCII 部分 2.633、非 ASCII 1.432、
跨类 BPE 节省 0.198811 token/少数类字符。估算器对该材料偏差 **+1.7%（偏保守）**。
纯 ASCII / 纯 CJK 材料不受跨类修正影响（单类无可合并边界）。

**未放宽的边界**：模型物理窗口 `allowed_input_tokens=800000` 未动；`_REVIEWER_WIRE_HEADROOM`
由 0.8 改为 0.98（其语义是"给 framing/协议留余量"，实测 framing 仅约 1K token，
原 0.8 是 160K token 的无依据保守值）；未跟踪文件 200KB 单文件闸未动；
`reports/` runtime 投影规则未动；敏感路径拒绝未动；非 reviewer 的子代理 wire 完全未改。

**双侧实测（RULE-AI-35）**：
- 放宽侧：本分支真实材料 1,936,899 字符 → 预检 ACCEPTED，child 亦 ACCEPTED（估算 775,239 token ≤ 784,000）。
- 拦截侧：×1.1 / ×1.2 / ×1.5 / ×2.0 的材料全部 REFUSED（`reviewer_input_too_large`）。
- 回执：`evals/results/review_cap_change_20261023/calibration.txt`、`gate_outcome.txt`。

**仍存的独立阻塞（非上限维度）**：`review_untracked_file_limit` —— 工作区 42 个未跟踪文件
（并发工作线的 `src/llm_loop/realtime/*`、`tests/realtime/*`）超过 40 个上限。
上限改动无法清除该阻塞；需并发工作线自行提交或搁置。

---

## 12. 评测框架真实 LLM 路径失效（2026-10-23，P1 期间发现并修复）

> 关联：`docs/EVAL-PLAN-LFL-20261023.md` §18 ｜ 复算：`uv run --no-sync python scripts/run_eval.py --scenarios <file> --output <dir>`

### 12.1 现象

真实 LLM 模式下，**全部场景 0/N**，且报告里 `model_used=""`、`rounds=0` —— 模型根本没被调用。回答内容恒为：

```
[写入被拒] 你的消息未通过校验：leak.channel_denied …
```

### 12.2 根因（已读源码定位，非推测）

1. **R8.24-D 修订②把 `LFL_LEAK_GUARD_MODE` 改为 fail-closed（enforce）**（2026-09-16 typed settings 迁移引入）。`user_ingress_guard.guard_user_write` 在 role=user 写入且**无 ingress 凭据**时直接拒绝。
2. `scripts/run_eval.py` 的 `engine.run(sid, prompt)` **未传 ingress** → 全部被拒。
3. 附带发现：`run_eval.py` 取 key 只认 `DEEPSEEK_API_KEY`/`LLM_API_KEY`，**不读 provider 声明的 `api_key_env`**（如 minimax 用 `MINIMAX_API_KEY`）→ 换 provider 即 "缺少 api_key"。

**为何此前未被发现**：最后一次真实 LLM 评测是 2026-08-16；此后 `user_ingress_guard.py` 于 2026-09-16 重构，评测框架未同步适配 → **域内评测的真实 LLM 路径自那时起即处于静默失效状态**（dry 路径不受影响，故 CI 一直绿）。

### 12.3 修复（已落盘 + 回归测试）

| 修复 | 位置 | 口径 |
|---|---|---|
| 传入 test_harness ingress 凭据 | `scripts/run_eval.py` `engine.run(..., ingress=issue_test_ingress())` | **不改 guard 的 fail-closed 语义**，只补齐本入口的合法凭据；`issue_test_ingress` 是 spec 5.3.3-4a 明确的测试后门，生产代码禁止使用 |
| 按 provider 的 `api_key_env` 解析 key | `scripts/run_eval.py` `_resolve_api_key()` | 顺序：provider 声明 → `DEEPSEEK_API_KEY` → `LLM_API_KEY`；无凭据时抛错，不静默用空 key |

回归测试：`tests/unit/test_eval_runner_ingress_and_key.py`（5 项，全 PASS）。

### 12.4 登记意义

这是一条**"静默失效"**红线：CI 只跑 `--dry`，而 dry 路径不经过 ingress guard → 框架与真实运行时的接口断裂在 CI 中不可见。→ 列入 P3 治理红线集候选（"评测框架与运行时集成断裂"类）。


---

## 13. PYTHONPATH 指向 release 快照 → 本地代码改动静默失效（2026-10-23，P1 期间发现并修复）

> 关联：`docs/EVAL-PLAN-LFL-20261023.md` §18.5 ｜ 复算：`uv run --no-sync python -c "import llm_loop.eval.verdicts as v; print(v.__file__, len(v.VERDICTS))"`

### 13.1 现象

本会话为 v2 场景集新增了 7 个判定谓词并修复了 runner，但评测跑出来**全部场景恒 0/1**。多次排查（守卫凭据、模型名、api_key、谓词语表）全部"看起来对"，本地复算谓词返回 `True` 而 runner 返回 `False`。

### 13.2 根因（已用运行时事实定位，非推测）

```
$ uv run --no-sync python -c "import llm_loop.eval.verdicts as v; print(v.__file__, len(v.VERDICTS))"
.../.releases/48e87f3982340ee73dd9f9b070608222b28a9976/src/llm_loop/eval/verdicts.py 6      # ← release 快照，只有旧 6 个谓词

$ PYTHONPATH= uv run --no-sync python -c "..."
<repo>/src/llm_loop/eval/verdicts.py 13                              # ← 工作树，13 个谓词
```

- 本机环境变量 `PYTHONPATH` 指向 `.releases/48e87f39.../src`（**发布快照**），且排在 `sys.path` 靠前位置。
- `scripts/run_eval.py` 原先只做 `sys.path.insert(0, _PROJECT_ROOT)`（**项目根**）。而 `llm_loop` 包位于 `src/` 下，项目根并无该包 → `import llm_loop` **落到 PYTHONPATH 的 release 快照**。
- 结果：**本会话所有 `uv run` 跑的都是 06:14 的 release 快照源码**；工作树的新谓词与修复全部未加载。快照与工作树的**源码级差异仅 `verdicts.py` 一处**（其余为 `__pycache__` 与 `src/data`）→ 恰好掩盖了问题：除新谓词外，其余行为与工作树一致，难以察觉。

### 13.3 修复

`scripts/run_eval.py` 改为**把 `src` 显式插到 `sys.path` 最前**（与 `eval/rules/selfcheck.py` 及 pytest 入口一致），项目根仍保留（兼容以根为基准的相对路径读取）。

### 13.4 对既有结论的影响复核（已做，非默认无影响）

| 结论 | 是否受影响 | 依据 |
|---|---|---|
| §18.4 CI 红数对账（3 red / 10039 passed） | **不受影响** | 快照与工作树源码差异仅 `verdicts.py`；该文件只新增谓词与 `run_verdict` 的 kwargs 过滤，不改变既有 6 个谓词的行为；新增单测亦全 PASS |
| selfcheck 84/84 | **不受影响** | `eval/rules/selfcheck.py` 自己 `sys.path.insert(0, "src")` → 一直加载工作树 |
| `domain_baseline.py --verify`（123 sha256 复算） | **不受影响** | 该脚本只读 JSON 产物与文件哈希，不 import `llm_loop` 业务逻辑 |
| v2 场景集真实 LLM 判定 | **受影响，已随 §13.3 修复** | 此前恒 0/1 的结论全部作废，需重跑 |

### 13.5 登记意义（→ P3 红线集候选）

这是**"静默失效"最高危的一类**：环境变量让本地代码改动完全不生效，但**没有任何报错**，且大部分既有行为与工作树一致（只差新增部分）→ 极易被误判为"我的代码有问题"，浪费大量排查时间。

→ P3 红线集应含一条：**"评测执行环境与被测代码来源一致性"**（断言：评测进程实际加载的 `llm_loop` 源码路径 == 工作树路径；不等则判 FAIL）。
→ 建议在 `eval/rules/selfcheck.py` 增加该断言（可复算、无副作用）。
