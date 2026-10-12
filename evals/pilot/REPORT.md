# Local Agent Pilot 评测报告（Cline + Deep Agents vs LFL）— v0.1 修订版

日期：2026-09-12 · 执行人：LFL（goal GOAL-20260912-f4655ad5 T4）· 修订：v0.1，外部交叉审计后修正失败归因与 t12 口径

## 1. 目的与口径

在**同一本地模型权重**（Ornith-1.5-35B-A3B-MLX，LM Studio, 127.0.0.1:8901）上，对比三个 agent harness 完成同一组 12 个小型 coding 任务的表现：

- **lfl**：本仓库 llm-first-loop（plan 模式，默认模型；v0 原始 33 条 run 未做 per-run DATA_DIR 隔离，属已知口径缺陷）
- **da**：Deep Agents **0.7.13 + AgentPilot 最小 4-tool adapter**（read_file / write_file / list_dir / run_command，ChatOpenAI，temperature=0.2，自定义 system prompt）——非 Deep Agents 完整产品能力 qualification
- **cline**：Cline headless 3.0.61（`--json`，openai-compatible provider，CLI 默认推理契约）

**口径声明**：这是 same-model-weight / same-inference-server 的 **harness 对比**，不是完全控制推理参数的 agent-only A/B。三者的 system prompt、tool schema、采样参数（如 da 显式 temperature=0.2）、context 管理（cline compaction、lfl reasoning/cache contract）各不相同。这些差异在本评测目的下属于 harness 产品能力的一部分，但结论表述不得超出该口径。

每任务 ×3 次重复，判定均为**程序化验收**（文件存在/内容匹配/命令输出匹配），无人工评分。原始 `results.jsonl` 112 行，含 4 条历史重复，按 `(agent,task,run)` 取最新 ts 去重后 **n=108**。

## 2. 任务集（12）

均为小型、程序化可判定的任务，每 run 独立 tmp 工作区：

| ID | 任务 | 验收 |
|----|------|------|
| t01_read_first_line | 读 probe.txt 第一行原文写入 answer.txt | 内容 == `PYTHQN-MARKER-L1`（含拼写陷阱） |
| t02_retry_transient | 运行 gen.py；首次必失败，需诊断后重试 | result.json == {ok:true, n:42} |
| t03_build_module | 写 fib.py + test_fib.py 并跑 unittest | fib(10)=55, fib(0)=0，测试退出码 0 |
| t04_fix_bug | 修 broken.py 的 median 缺陷（不许改测试） | 3 个既有测试通过 |
| t05_multi_file_sum | 读 a/b/c.txt 全部整数求和 | total.txt == 41 |
| t06_log_count | 数 app.log 中 ERROR 级别行数 | errcount.txt == 3 |
| t07_json_flatten | 展开 in.json 的 data.items 各 name | names.txt == alpha/beta/gamma（3 行） |
| t08_resume_todo | 按 README-TASK.md 补全 half_done.py 的 TODO | `python3 half_done.py` 打印 OK |
| t09_big_file_line | 取 big.txt（2500 行）第 2024 行 | line2024.txt == L2024 |
| t10_fs_invariant | 建 A.txt=keep、B.txt=drop 后删 B.txt | A.txt 存在且 == keep，B.txt 不存在 |
| t11_env_facts | 用命令实取 whoami/pwd 写 facts.json | 值与真实回执一致（事实纪律探针） |
| t12_interrupt_resume | 三阶段建 stage{1,2,3}.txt + mark.py 标记；第 25s 强杀一次后续接 | marks.json == [p1,p2,p3]，三文件内容 one/two/three |

任务定义源码：`evals/pilot/tasks.py`（prompt/setup/verify 全部确定化，无网络依赖）。

注：t11 初版 prompt 未明确要求先 `cd` 工作区，首跑记录了错误 cwd；修正 prompt（明确 `cd {ws}` 后再运行）后三个 harness 均以修正版计入统计（分析脚本按 (agent,task,run) 取最新记录去重）。

## 3. 结果（v0.1 修正口径）

数据：`results.jsonl`（raw 112 行，按 (agent,task,run) 取最新 ts 去重后 n=108）；本节统计由独立脚本直接从去重后原始记录重算，不沿用 v0 汇总数字。

### 3.1 结果状态分类

v0.1 起结果状态分为 `PASS / TASK_FAIL / INFRA_FAIL / ADAPTER_INVALID / TIMEOUT`（v0 只有 pass 布尔值，把适配器/基础设施错误混入了任务成功率）。

| agent | 普通任务 t01–t11 | t12 中断-恢复 | v0 旧口径（纯 pass） |
|-------|------------------|---------------|----------------------|
| lfl | **32/33**（t06 r2 = TASK_FAIL） | v0：3/3 通过但语义为 workspace-recovery（P0-1）；**v0.1 复测 3/3 + mid-kill 1/1 均为 session-resume，`session_continuity=True`，sid 机械匹配**（§3.2-P0-1 复测） | 35/36（97.2%） |
| da | **33/33** | 3/3 通过；语义为 **new-session-same-workspace-by-design** | 36/36（100%） |
| cline | **33/33** | **3× ADAPTER_INVALID**（CLI 调用错误，恢复阶段从未启动）；后续 smoke 判定 3.0.61 headless `--id` resume **UNSUPPORTED**（§3.4） | 33/36（91.7%） |

- **cline 的 91.7% 不能解释为模型/agent 任务成功率**。若需衡量"适配器整体可运行率"，应另设 `operational_pass_rate` 单独报告。
- 三组 pooled Wilson CI 大面积重叠，且 36 样本实为 12 任务 × 3 重复、失败高度聚类（lfl 全在 t06、cline 全在 t12），**pooled CI 不适合作为主要显著性依据**。正式版应使用 task-level / hierarchical bootstrap，并同时报告 tasks fully passed / partially failed / infra invalid。

唯一真实任务失败（t06_log_count，lfl r2，TASK_FAIL）——**v0 归因已修正**：

- v0 表述"数对了 ERROR=3 但未写 errcount.txt（完成纪律缺失）"**不成立**。
- 原始记录的 agent 最终叙事为："`app.log` 不存在，无法统计，因此没有写入 errcount.txt（不会凭空编造数字）"。而任务 setup 确定性生成了 app.log（INFO×2 / ERROR×3 / WARN×1）。
- 真实分类：**workspace/tool 事实获取失败**（工具作用域/路径定位错误）——模型基于"文件不存在"这一错误事实做出了逻辑自洽但任务上错误的停止决定。该 run ok_run=true、7 轮、6 次工具调用、84.3k 入 tokens，最终由 verifier 判 FAIL。
- 已列为 LFL 正式 regression case：工具调用"成功返回" ≠ 使用了正确作用域 ≠ 取得了正确事实（与 First-Call-Ready 工作直接相关；同时印证 final narrative 不能取代工具轨迹事实）。

### 3.2 t12 中断-恢复：两项 v0 结论被原始数据推翻

**P0-1：v0 的"lfl 原生 session resume 3/3"无证据支持。（v0.1 复测已闭合）**
runner 设计意图是中断后取 phase1 日志中的 `[会话 ...]` id 并以 `--session <sid>` 恢复，但实际传入 `run_lfl_session()` 的是 `rec["phase1_log"]`——该字段已被截为**尾部 800 字符**，会话行不在其中 → sid 恒为空 → `--session` 从未被附加。机械证据：v0 三条 t12 lfl 记录的 `phase1_sid` 字段均为空串。
复测发现**更深一层的根因**：SIGKILL 命中 mid-turn 时，CLI 从未打印 `[会话 …]` 行——stdout 本来就没有 sid（800 字符截断只是次生）。v0.1 修复因此是双通道：stdout 提取失败时，从隔离 DATA_DIR 的 `sessions/` store 直接解析 phase1 sid（kill 后、resume 前 store 内仅有 phase1 会话文件，无歧义）。
**复测结果（data/results_v01_t12_retest.jsonl + results_v01_t12_midkill.jsonl）**：
- 正式 3 runs：3/3 PASS，`interrupted=false`（phase1 首 turn 在 25s 窗口内自然完成），stdout 通道取 sid，`session_continuity=True`，`resume_semantics=session-resume`，workspace 内仅存**单个** session 文件（resume 续用原会话）。
- 强制 mid-kill（interrupt_s=8）：PASS，`interrupted=true`，store 通道取 sid（单元验证于真实被杀 store：正确选中 phase1 会话），resume 以同一 sid `9b9b1c76` 续接，6 轮 / 5 工具调用 / 54.5k tokens——真实续作而非重放。
- v0 的 3/3 记为 workspace-recovery 不变；**v0.1 起方可在报告中声明 lfl 原生 session resume 通过 mechanical qualification（3/3 + 1/1）**。
- 口径注意：25s 窗口下 phase1 是否被真杀是时序敏感的（本批自然完成、上批被杀）；v1 正式矩阵建议将 t12 的 interrupt_s 降到首 turn 中位时长以下（如 8s）以保证 mid-turn kill 确定性。

**P0-2：v0 的"cline 新建工作区并在新 ws 完成三阶段"不成立。**
三次记录均为 `resume_ok_run=false`、`resume_dur=1.0–1.2s`，stderr 完全一致：`JSON output mode requires a prompt argument or piped stdin (interactive mode is unsupported)`。恢复阶段 agent 从未启动，**不存在任何可推断的工作区行为**（v0 关于 `0ec65d→bdbaed` 换 ws 并完成 marks.json 的描述撤回，无轨迹支撑）。
旁证：普通任务 33/33 均成功解析 `conv_*` session id（parser 正常）；本机 cline 3.0.61 CLI 存在 `--id <session-id>` resume 能力，属 v0 runner 未正确构造调用。
正式分类：**3× ADAPTER_INVALID，尚未形成有效 resume qualification**。

**结论：本轮 t12 不能用于三方 Session Continuity 排名。**

### 3.3 时长（秒；分位数取线性插值）

v0 口径有两个系统偏差：t12 只计 `resume_dur`（漏掉固定 25s 中断前时长）；cline 三个 1.0–1.2s 的 invalid 恢复进入均值，压低其平均。三种口径重算如下：

| 口径 | lfl | da | cline |
|------|-----|-----|-------|
| A：v0 原口径（36 条，t12=resume_dur） | 35.5 / 47.4 / 84.4 | 42.1 / 68.3 / 140.4 | 40.5 / 49.7 / 88.2 |
| B：A + 回加 25s | 35.5 / 49.5 / 84.4 | 42.4 / 70.4 / 140.4 | 40.5 / 51.8 / 88.2 |
| **C：共同有效任务 t01–t11，仅成功 run**（n / median / mean / p90） | 32 / **32.8** / 46.2 / 83.0 | 33 / 39.9 / **68.0** / 140.7 | 33 / 51.9 / 54.1 / 91.2 |

C 口径下 lfl 成功 run 中位最短、da 长尾最明显（p90≈141s）、cline 居中。**但 latency 排名只作趋势**：v0 按 agent 成块运行、顺序未随机化，8901 prompt cache 热度、OS 文件缓存、机器负载按时段混入速度测量。正式版采用 randomized block / Latin-square 后才可讨论速度差异。

### 3.4 解读（v0.1）

1. 同权重模型、11 个有效普通确定性任务上：da minimal adapter 与 cline 均 33/33，lfl 32/33。差距在失败模式而非成功率。
2. lfl 唯一真实失败暴露的是 **workspace/工具事实定位问题**，不是任务求解能力问题。
3. t12 本轮未测准：runner 存在两处缺陷（lfl session id 未传递、cline resume 调用无效），三方 Continuity 排名待修复后重测。

## 4. v0.1 runner 修复（已落盘）与 cline resume smoke qualification 结论

### 4.1 已落盘修复

1. **P0-1（已修复并复测通过）**：`run_lfl_session` 改收 phase1 全量日志提取 sid，并从隔离 store 反查完整 id；增加机械断言——resume 后 CLI 报告的 session 前缀必须等于 phase1 sid 前缀（`session_continuity` 布尔 + `resume_semantics` 枚举：session-resume / new-session-same-workspace / resume-failed）。**追加**：mid-kill 时 stdout 无 sid，增加 store 通道（`_lfl_newest_session_sid`：kill 后、resume 前取 store 内最新 mtime 会话文件）；复测见 §3.2-P0-1（3/3 + mid-kill 1/1）。
2. **P0-2 修订**：cline `--id <sid>` 调用保留（失败即自证），但 2026-09-12 smoke qualification 证明失败根因不是本方 adapter 调用缺陷，而是 **CLI 能力边界**（见 4.2）→ 守卫消息现归类 `unsupported-headless-resume` → 新状态 **UNSUPPORTED**，与 ADAPTER_INVALID 区分；v0 历史 3 条仍按当时口径记 ADAPTER_INVALID。
3. 状态分类 `_classify`：PASS / TASK_FAIL / INFRA_FAIL / ADAPTER_INVALID / **UNSUPPORTED** / TIMEOUT。
4. t12 完整 wall clock：`dur = interrupt_s + resume_dur`。
5. 输出改追加式，分析端按 (agent,task,run) 取最新 ts 去重（收敛掉 `aggregate.py` 尾部 K=3 的第二套规则，正式 qualification 只保留一个 canonical aggregator）。
6. LFL per-run `DATA_DIR` 隔离（`.lfldata` per ws）；`--randomize` randomized block；`--manifest` 冻结三方版本 / model identity / runner 与 tasks SHA / seed。
7. manifest 冒烟已过：lfl_commit=b5717ac0、cline 3.0.61、deepagents 0.7.13、model endpoint 可达（注意：8901 当前自报 id 为 `Qwen/Qwen3.5-35B-A3B` 等，与历史 ornith 命名并存，manifest 记录 raw 字符串）。

### 4.2 cline resume smoke qualification（2026-09-12，结论：**未通过——headless resume 在当前 CLI 不存在**）

在确定性 t12 语义下系统排除全部调用形态（同一 conv_* 会话、同一 ws）：

| # | 调用形态 | 结果 |
|---|---|---|
| 1 | `--json "prompt" --id` | ✗ `--id cannot be combined with --json` |
| 2 | `--json` + 管道 stdin + `--id` | ✗ 同上守卫 |
| 3 | `--storage-id` + `--json` + `--id` | ✗ 同上守卫 |
| 4 | `--id` 无 `--json`（非交互 shell） | ✗ `interactive mode requires a TTY` |
| 5 | `--id --auto-approve true`（无 json） | ✗ 同 TTY 守卫 |
| 6 | `--id --yolo` | ✗ 同 TTY 守卫 |
| 7 | `--id --yolo --json` | ✗ json 组合守卫 |
| 8 | `--id --zen` | ✗ `--zen is not compatible with interactive mode` |

旁证：二进制内字符串 `interactive mode requires a TTY` 紧邻 resume 逻辑；当日 nightly `3.0.61-nightly.1789129344` 同样未修；PTY 探针（`script` + 管道）TUI 渲染但 turn 未提交、会话文件未增长且进程挂起，不具 benchmark 级确定性。

**结论**：`--id` resume 在 cline 3.0.61（及当日 nightly）只存在于交互 TTY 路径；AgentPilot v1 矩阵中 cline t12 记 **UNSUPPORTED（headless）**，不计任务成功率、不归 adapter 缺陷；待上游提供 headless resume 后由 runner 的守卫分类分支自动恢复真实 qualification。Session Continuity 三方对比在 v1 中表述为：lfl session-resume（复测已通过，§3.2-P0-1）vs da workspace-recovery（语义标注）vs cline unsupported-headless。

## 5. 下一步（优先级）

1. ~~cline `--id` resume 单独 smoke qualification~~ **已完成（2026-09-12）：未通过，headless resume 当前不存在，t12 记 UNSUPPORTED（§4.2）**；跟踪上游版本，恢复后 runner 守卫分支自动进入矩阵；
2. ~~t12 复测~~ **已完成（2026-09-12）：lfl 3/3 + mid-kill 1/1，`session_continuity=True` / `resume_semantics=session-resume` / sid 机械匹配（§3.2-P0-1；data/results_v01_t12_retest.jsonl、results_v01_t12_midkill.jsonl）**；v1 正式矩阵 t12 建议降 interrupt_s 至 ~8s 保证 mid-turn kill 确定性；
3. ~~补 First-Call-Ready telemetry~~ **已完成（2026-09-12）：双层落地——runtime raw 18 字段（`telemetry.py::extract_raw` + runner 落盘 `first_call`/`fcr_events` 原始事件流，纯事实零语义判断）+ scorer 9 字段（`score_fcr` 离线复算，selection 由 task oracle `first_tools` 判，`first_call_ready = selection × mechanical` 两事实派生；`_LEGIT_SIDE` 绕路不判错）**；评价维度拆为 Outcome / Efficiency / Continuity / First-Call-Ready（`analyze.py` 已输出，v0.1 起生效）；
   - **usage 口径（2026-09-12 修订）**：lfl store 的 tool-call assistant turn per-turn usage 未持久化（记 0，仅末 turn 记 run 级汇总），故 `tokens/cache_hit_to_first_*` 对 lfl 为 unavailable（`null`，usage-missing ≠ 0，`telemetry.py::_usable_usage`），不参与跨 harness 数值比较；`first_tool_name / selection_correct / first_call_ready / rounds / time_to_first_*` 仍有效。cline 工具级成败在 `--json` stream 中不可测 → 对应字段 `None` + `.cline_stream.jsonl` 全量事件流落盘备查；
4. ~~冻结 v1 manifest~~ **已完成（2026-09-12，Gate 4.0 冻结/预检）**：manifest freezer revision 2 落盘并验证——
   - **冻结内容**：runner/tasks/telemetry/scorer 四 SHA；模型身份三重指纹（`model_dir_fingerprint` 22 个模型文件 per-file sha256 + `/v1/models` 原始 JSON + 8901 listener pid/cmdline）；`harness_contracts`（含 da `temperature=0.2`、cline expected_model_ref）；`task_oracles`（first_tools / expected_failures / timeout_s / interrupt_s 每 task 记录）；`t12_protocol` 与 `fcr_caliber` 口径全文写死；
   - **计划冻结**：Latin-square 整表（task×run 双错位轮换，seed 固定）+ `execution_plan_sha256`；同 workdir 重跑时 freeze 校验不一致即拒绝（防止事后换签）；`--start-index`/`--max-items` 支持断点续跑；`--plan-only` 干跑不执行；
   - **已验证**：`--tasks` 零匹配 exit=2 显式报错（canonical ID only，短别名不静默）；t01–t03×3 agents seed=0 计划表实现 ABC/BCA/CAB 跨 task 错位；`analyze.py` 对 v0 全量重算口径 A/C + ADAPTER_INVALID 分类回归通过；summary 已区分 all-history / this-session 计数；
   - **诚实缺口**：`model_server_runtime` interpreter 版本探测 unavailable（8901 进程 ps cmdline 仅暴露 macOS framework 二进制，其中无 mlx_lm）——模型身份已由目录指纹 + 服务端 `/v1/models` 双重钉死，interpreter 版本不构成身份依赖；
   - **下一步**：三方 preflight block（1 task × 3 agents 真实执行，确认各自产出 run_id/telemetry/scorer）→ 99-run 主矩阵（t01–t11×3×3）+ t12 分离 qualification（lfl/da mid-kill interrupt_s=8 各 ≥3；cline 记 UNSUPPORTED 不产生伪数据）；矩阵开始后冻结代码，measurement-invalidating bug 则废弃受影响批次、manifest revision 升级重跑；
5. t06 列为 LFL 正式 regression case（workspace/tool 事实定位）。

## 6. 局限

- 单机单模型、12 小任务、3 重复；task-level 聚类使 pooled Wilson CI 解释力有限。
- v0 lfl 未做 per-run DATA_DIR 隔离；t12 复测起隔离，与 v0 原始 33 条存在口径差异（manifest 已记录）。
- 执行顺序未随机化（agent 成块运行），cache/负载按时段混入 latency；采样与推理契约非完全统一（harness 对比目的下可接受，已明示）。
- da 为 Deep Agents 0.7.13 最小 4-tool adapter，不代表完整产品能力。
- lfl 为本仓库开发中版本，存在自评偏置风险；判定脚本对所有 harness 一致。
- final narrative 不能取代工具轨迹事实（t06 为反例，已收录为 regression case）。
