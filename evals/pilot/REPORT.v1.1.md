# AgentPilot v1.1 结果报告（降级采信版）

> **状态：降级采信（degraded acceptance）。** 本数据集因验收门 FAIL（GOVERNANCE.v1.md §9.2：执行窗口内 LFL 冻结身份漂移）本应不予采信；2026-09-12 23:53/23:54 用户裁决放弃重跑（redo#3 不发起），按 §9.2 选项二"降级采信+漂移注记"发布。**引用本报告任何数字必须同时携带 §3 漂移注记**；不带注记的摘引视为违规引用。采信层级低于 v1 封盘正式数据集（REPORT.v1.md）。

## 1. 数据身份（manifest 机械钉扎；2026-09-12 21:37 验收复核 + 2026-09-13 发布前复核）
- workdir：`/private/tmp/agentpilot-v11-formal-20260912`（108 行，ts 20:47:20–21:37:02，PID 63388 自然退出）
- 钉扎：`lfl_commit`(声明)=1437be74…；`runner_sha256`=a7480edf…；`tasks_sha256`=d481735b…；`telemetry_sha256`=0d559f39…；`scorer_sha256`=33de85e2…；`execution_plan_sha256`=570be8c6…
- 执行序：latin-square（seed 20260912，三臂交错）；interrupt=True
- 模型：8901 单物理模型 `ornith-ai/Ornith-1.5-35B-A3B-MLX`（三臂同权重、同推理服务；推理契约随 harness，见 §4）
- analyzer：`evals/pilot/analyze.py` @ 226a9010（L85 连续性键名修复版）；2026-09-13 复跑逐项复现 §2

## 2. 结果（修正后 analyzer；2026-09-13 复现）

**状态矩阵汇总：**

| 臂 | status | task-level（剔除 invalid/unsupported） | t12 语义 |
|---|---|---|---|
| lfl | 36/36 PASS | 36/36 | session-resume ×3，`resume_session_continuity`=3/3（sid 逐位前缀匹配 c62532e3 / 332b8cc1 / 7b5f23c2） |
| da | 36/36 PASS | 36/36 | new-session-same-workspace-by-design ×3 |
| cline | 33 PASS + 3 UNSUPPORTED | 33/33 | unsupported-headless-resume ×3（设计性不支持，dur=None，非失败） |

**t12 有效恢复时长**（PASS only，不产生伪时长）：lfl med 20.9s / mean 19.2s；da med 42.1s / mean 40.3s。

**时延 caliber C**（t01–t11 成功 run，n=33；median / mean / p90，秒）：

| 臂 | med | mean | p90 |
|---|---:|---:|---:|
| lfl | 16.4 | 19.3 | 31.7 |
| da | 24.5 | 29.9 | 49.3 |
| cline | 32.3 | 33.7 | 44.7 |

**First-Call-Ready（双层：raw 机械层 / scorer 层）：**
- lfl：ok_signal=True；args_mech_valid 33/33；selection 18/33；first_call_ready 18/33；directness 0.55；fail_raw 0.36/run；ttfmv med 4.91s
- da：ok_signal=True；fail_raw 0；selection 7/33；first_call_ready 7/33；directness 0.21；tokens_to_fmv med 2,576
- cline：**ok_signal=False（原始遥测缺失）**；仅 scorer 部分值（selection 11/33，directness 0.33），不得与另两臂 raw 层并列比较

**v1→v1.1（同任务集 t01–t12）**：lfl t06 2/3→3/3；caliber C 中位 32.8→16.4 / 39.9→24.5 / 51.9→32.3，三方同步下降 38–50%（见 D4）；t12 连续性 3/3 复现 v1 封盘 §3.3 结论（P0-1 修复可复现）。

## 3. 漂移注记（引用必带）

- **D1 LFL 代码身份漂移（本数据集降级的直接原因）**：manifest 声明 lfl_commit=1437be74，但运行期 LFL 经 editable `.pth` 解析到活动仓库 src，非冻结树。窗口内 35fa47c9（`src/llm_loop/tools/`：edit_file / execute_command / evidence_tools / registry，37+/2−，内容为模型可见工具描述文本，无机制改动）于 20:55:30 fast-forward 入主线。30/36 lfl 行 post-drift（全 PASS）、6 行 pre-drift；t12 lfl r2 pre、r1/r3 post，`resume_session_continuity=True` 两侧均成立 → 连续性结论对漂移稳健；但 lfl 臂整体代码身份 = 活动仓库（1437be74..35fa47c9 混合），非单一 commit。
- **D2 redo#1**（22:25–23:01，冻结隔离树）：lfl 臂 36× INFRA_FAIL（dur 0.0–8.1s；冻结环境未注入 LLM_API_KEY）→ **不存在有效的冻结 LFL 复现**；da 36/36 PASS、cline 33 PASS + 3 UNSUPPORTED，与正式跑完全一致 → da/cline 两臂获得一次隔离复现佐证，结果稳定。
- **D3 redo#2 终止**：启动前熔断——manifest lfl_commit 字段漂移（3c0cf042→0174af11），根因是 §11 预声明自身提交晚于冻结（先冻结后提交的时序缺陷），非数据问题。redo#3 未发起（用户裁决）。
- **D4 环境漂移（跨版本比较失效）**：v1→v1.1 三臂 caliber C 中位同步下降 38–50%，da/cline 不经 src/llm_loop 亦同步下降 → 成因是机器/服务端缓存与负载状态（未核），**非** D1 漂移提交。跨版本（v1 vs v1.1）时延比较无效；v1.1 窗口内三臂比较仍有效（latin-square 交错、同窗同序）。
- **D5 cline FCR 遥测缺失**：ok_signal=False，raw 层不可用（见 §2），三臂 FCR 对比不完整。

## 4. 解释规则
- 本轮为 **same-model-weight / same-inference-server 的 harness 对比**（Ornith-1.5-35B-A3B-MLX @8901），非推理参数受控的 agent-only A/B；温度/采样/system prompt/tool schema 随 harness，属被测能力一部分。
- t12 三种语义（session-resume / workspace-recovery / unsupported）不同源不同义，不得拼池计成功率。
- 时延结论限本窗口：lfl 中位最短（16.4s），但单机单窗口 pilot + D4，不宣称统计显著速度优势。
- 结论摘要：11 个普通确定性任务上三臂 task-level 均 100%（36/36、36/36、33/33，invalid/unsupported 剔除口径）；LFL 唯一具备并实证原生 session-resume（3/3，sid 连续）；v0 报告对 lfl t06 的"未写 errcount.txt"归因已由 v1/v1.1 数据修正为 workspace/tool 事实定位问题，且 v1.1 中不再复现（3/3）。

## 5. 恢复完全置信的条件（v1.2，未执行）
按用户裁决（2026-09-12 23:53）不发起。若未来执行：先修 §11 时序缺陷（commit 先于冻结）与冻结环境密钥注入，重跑单次冻结矩阵（预 G-pre 亚秒 INFRA 熔断），通过 §8-C 验收门后方可作为正式 v1.1/v1.2 数据集替代本报告。

---
关联：GOVERNANCE.v1.md §8–§12；REPORT.v1.md（v1 封盘正式数据集）；REPORT.md（v0 历史存档）。
