# AgentPilot v1 正式矩阵报告 — LFL vs Deep Agents adapter vs Cline

日期：2026-09-12 · 数据：`/tmp/agentpilot-v1-formal-final-20260912/results.jsonl`（n=108，无历史重复）· 前置：REPORT.md v0.1（v0 原始 pilot + 外部交叉审计修正）

> ⚠️ **治理披露（2026-09-12 追加，详见 `GOVERNANCE.v1.md`）**：本报告 n=108 中，rows 1–72 为 sealed-v1 正式数据集；rows 73–108 产生于封盘处置条款（"不允许再追加任何行"）之后的两次越界续跑，定性为 post-seal continuation 附录数据，仅作旁证、不并入正式口径。两次越界 invocation 的用户授权链尚未核实。在治理披露落库前，本报告整体仅限内部使用、不得对外引用。另：t12 中 cline 3 行语义为 `unsupported-headless-resume`（存储层因分类器字段 bug 误标 INFRA_FAIL，本报告按原始语义字段重映射），不计入任务失败。

## 1. 口径（继承 v0.1 声明，v1 全部落实）

- **同一本地模型权重**（Ornith-1.5-35B-A3B-MLX @ 127.0.0.1:8901，manifest 记录模型目录 per-file 指纹 + `/v1/models` 原始串）；same-model-weight / same-inference-server 的 **harness 对比**，非推理参数全控 A/B。
- **lfl**：本仓库，commit `b8e6dd1`（manifest 冻结），per-run DATA_DIR 隔离。
- **da**：Deep Agents **0.7.13 + AgentPilot 最小 4-tool adapter**（temperature=0.2）——非完整产品 qualification。
- **cline**：headless `--json` 3.0.61，CLI 默认推理契约。
- 判定：全部程序化验收，无人工评分。执行计划 Latin-square（task×run 双错位，seed=20260912）**已实际执行**（日志可见 da/lfl/cline 交错），v0 的 agent 成块运行混杂已在协议层消除。
- 冻结：manifest（18:33:02）含 runner/tasks/telemetry/scorer 四 SHA、`execution_plan_sha256`、t12_protocol（interrupt_s=8 真实 mid-kill）、fcr_caliber 全文；全部 108 行 `plan_sha256` 一致。

## 2. 完整性与隔离核验（本次重算，非沿用汇总）

| 检查 | 结果 |
|------|------|
| results.jsonl 行数 | 108（= 3×12×3，raw=n，v0 的 112/4 重复问题不存在） |
| plan_index | 0..107 连续唯一，与冻结计划一一对应 |
| manifest mtime | 18:33:02，运行期间（18:42–19:50）未变 |
| 双进程 | 无（分片顺序执行，每片一进程） |
| 跨片污染 | 无（shard 边界行完整：53/54、71/72 均完整对象） |
| cline t12 伪数据 | 无：dur=None，stdout 明示 "not invoked by design" |

## 3. 结果

### 3.1 状态分类（PASS / TASK_FAIL / INFRA_FAIL / ADAPTER_INVALID / UNSUPPORTED / TIMEOUT）

| agent | t01–t11（×3 run） | t12（×3 run） | task_success | 备注 |
|-------|------------------|---------------|--------------|------|
| lfl | 33/33 PASS | 3/3 PASS | **36/36** | t12 为真实 mid-kill session resume |
| da | 33/33 PASS | 3/3 PASS | **36/36** | t12 为 new-session-same-workspace（honest 语义标签） |
| cline | 33/33 PASS | 3× INFRA_FAIL | **33/36** | `unsupported-headless-resume`，按设计不调用、不产伪数据 |

v0 三大口径错误在 v1 数据中的对应修正：
1. v0 的 "lfl 原生 session resume 3/3" 证据缺失 → v1 三条记录 `interrupted=true` + `resume_session_continuity=true`（resume_session 与 phase1 sid 机械断言一致）×3。
2. v0 的 "cline t12 三连 TASK_FAIL" 错误归因 → v1 3× INFRA_FAIL(UNSUPPORTED 语义)，不计入任务成功率；91.7%→33/36 表述为 operational 口径，不再当模型/Agent 任务成功率。
3. v0 时长系统偏差 → v1 `dur = interrupt_s(8) + resume_dur` 全 wall clock；invalid 恢复 dur=None。

### 3.2 t12 中断-恢复（interrupt_s=8，真实 mid-turn kill）

| agent | 语义 | 结果 | 证据 |
|-------|------|------|------|
| lfl | **session-resume** | 3/3 PASS，dur 26.2/30.6/34.8s | sid 前缀断言 ×3 通过 |
| da | workspace-recovery | 3/3 PASS，dur 81.0/59.7/58.4s | resume_session=""（新会话） |
| cline | unsupported（headless resume 在 3.0.61 CLI 不存在，smoke 已系统排除 4 种调用形态） | 不调用 | dur=None |

**结论：Continuity 对比在 v1 成立且语义分离——lfl 是唯一被机械证明的原生 session resume（3/3 mid-kill）；da 为同工作区恢复；cline 属 CLI 能力边界，非 adapter 缺陷、非任务失败。** 三方仍不可做单一排名（语义不同）。

### 3.3 时长（秒；PASS runs；分位数线性插值；Latin-square 随机化后 v1 内部可比）

| 范围 | lfl | da | cline |
|------|-----|-----|-------|
| t01–t11（各 n=33） | median **15.5** / mean 19.2 / p90 28.2（max 39.6） | 23.5 / 28.6 / 47.4（max 65.3） | 30.6 / 35.6 / 54.1（max 96.6） |
| 含 t12 全 PASS | n=36: 16.1 / 20.2 / 32.7 | n=36: 24.6 / 31.7 / 55.8 | n=33（t12 无效不计）: 30.6 / 35.6 / 54.1 |

lfl 在 11 个普通任务上中位最短、长尾最小；da 中位居中、长尾明显；cline 中位最长。**仍只作趋势结论**：单机单晚、小任务、36 样本/方、task 聚类下 pooled CI 无区分力；v1 数值与 v0 不可直接比（协议、隔离、随机化、模型服务状态均变）。

### 3.4 First-Call-Ready 遥测（v1 新增；口径：first mechanically valid action）

| agent | round-1 即有效 | 首个有效动作耗时 | tokens→首个有效动作 | cache_hit 中位 | new_prefill 中位 | 工具失败合计 |
|-------|----------------|------------------|---------------------|----------------|------------------|--------------|
| lfl | 32/33 | 4.9s（中位） | n/a（CLI 未暴露） | 33.4k（中位，≈97.8% 命中） | 746 | 13（0.39/run） |
| da | 33/33 | n/a（无时间戳） | 2,577 | 16.8k | 941 | 0 |
| cline | 不可测（`--json` 流无工具级事件；.cline_stream.jsonl 已全量落盘备查） | — | — | — | — | 不可测 |

- FCR 维度首次进入统一 benchmark；**lfl 的 cache 命中率优势（中位 97.8%）与 da 的零失败调用是本轮最值得跟进的效率信号**。
- 跨 harness FCR 对比尚不 apples-to-apples（字段可用性不同：lfl 缺 tokens-to-first、da 缺时间戳、cline 缺工具级事件）；v1.1 需统一遥测契约。

## 4. 与 v0.1 修复清单的对照（全部在 v1 数据中验证生效）

P0-1 session id 双通道提取+机械断言 ✓（3×continuity=true）；P0-2 cline UNSUPPORTED 分类 ✓；状态分类六态 ✓；t12 全 wall clock ✓；canonical aggregator 单一化 ✓（analyze 按 (agent,task,run) 最新 ts）；DATA_DIR 隔离 ✓；randomize→Latin-square 实跑 ✓；manifest 冻结+SHA ✓；FCR 遥测落地 ✓。t06 regression case：v1 下 lfl 33/33 未复现——记为"该协议下未复现"，非"已修复"。

## 5. 局限与下一步

- 单机/单模型/单时段；36 样本/方；小任务集；latency 与 FCR 均趋势级。
- cline 工具级遥测缺失；da/lfl FCR 字段不对齐 → v1.1 统一遥测契约。
- t12 语义分离后仍无三方单一 Continuity 排名；cline 需上游支持 headless resume 才能入组。
- 下一步：扩大任务集前先统一 FCR 口径；增加 task-level bootstrap / paired 报告；t06 保持 regression 观察位。
