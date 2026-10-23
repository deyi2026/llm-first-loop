# 评测统计与判定纪律卡

> 版本：v1 ｜ 生效日期：2026-10-23 ｜ 状态：**生效**
> 配套：`docs/EVAL-PLAN-LFL-20261023.md` §4（九条纪律 D1–D9）｜ 归因器：`eval/rules/attribute.py`
> 实现锚点：`src/llm_loop/eval/verdicts.py`（`wilson_ci` / `VERDICTS` / `run_verdict`）

---

## 1. 九条纪律（报告模板必须逐条满足）

| # | 纪律 | 落地判据 | 自检命令 |
|---|---|---|---|
| D1 | 统一统计层 | Wilson 95% CI（复用 `wilson_ci`），n≥3；**同时报 pass@1 与 pass@K，禁止只报 best-of-K** | 检查报告含 `pass@1` / `pass@K` / CI 三字段 |
| D2 | 预算对齐 | 同模型 / 温度档 / 轮数 K / 每轮 token 上限；**必报 tokens 差** | 报告含 tokens 差字段 |
| D3 | 证据分级 | A = held-out Δpass@1>0 且同预算（可 promotion）；B = Δpass@K>0 且 tokens 不升（效率型）；C = 仅激发任务提升（**不得据此 promotion**） | 每条结论带 A/B/C 标记 |
| D4 | provider 矩阵 | 能力结论 ≥2 provider；主结论用 high 档；单 provider 必须显式标"不可外推" | 报告含 provider 列表；单 provider 有标注 |
| D5 | 污染与泄漏 | 外部题面只读不写；**只看 problem_statement / test_patch，不看 gold patch / 官方 commit**；cutoff 锚点 = 模型 API 注册日 | 逐例标注"自主/参考"，参考者不入自主分母 |
| D6 | **失败归因先于分数** | `unknown_agent_error` 占比 >30% → 标"不可用基线"，禁止进入能力比较 | `python3 eval/rules/attribute.py …` 输出末行判定 |
| D7 | 外部基准不做名次 | 只报"同模型换 harness 的差值"与"LFL 可达性/适配成本"；版本漂移由版本锁 + 题面 sha256 + dataset commit 兜底 | 报告无"排名第 N"类措辞 |
| D8 | 成本必报 | 每份结论附 tokens / 费用 / 时长 / 轮数；成本上升与通过率同表 | 报告含成本表；不可用时显式写"成本不可用"（**不得以 0 代替**） |
| D9 | 证据不足即 `insufficient` | 对证据做归属 / 口径 / 相关性三查，不通过则标 insufficient，不强行下结论 | 报告含 `insufficient` 字段 |

---

## 2. 统计量速查

- **Wilson 95% CI**：`wilson_ci(k, n)`（`src/llm_loop/eval/verdicts.py`）。n<20 时区间极宽，结论只能**方向性**表述。**引用本仓库的 CI 数字时用实算值**：`wilson_ci(7,27) = (0.1317, 0.4468)` → 13.2%–44.7%；`wilson_ci(7,79) = (0.0436, 0.1718)` → 4.4%–17.2%。
- **CI 重叠 ≠ 无差异**；CI 不重叠 ≠ 差异显著（需两比例检验或预注册检验）。
- 最小可检差异（双侧 α=0.05、power=0.8、两比例公式**估算**，p≈0.1–0.2）：n=30/臂 ≈ 25–30pp；n=60/臂 ≈ 20pp。
  → 含义：外部基准小样本分数几乎无法区分 harness 优劣；这正是 P2 必须用域内 held-out 而非公开榜单名次做结论的原因。
- 冻结任务集 + oracle + scorer 范式沿用 `evals/execution_efficiency_v2`；改题、改 oracle、改评分器一律记为新版本，**旧结论不自动继承**。
- **负结果同等呈现**（沿用 `docs/metrics/eval_2026081*` 报告纪律）。

---

## 3. 失败归因口径（D6 的执行细则）

`unknown_agent_error` 是 harness 兜底标签，**不含根因**，不得直接当作"agent 能力失败"计数。

| 归因组 | 根因 | 计入能力分母？ | 判据 |
|---|---|---|---|
| A_docker_build | 镜像/装配构建失败 | ❌ 否 | `Harness execution failed …: Command '['docker'…` |
| B_errno24 | 宿主 fd 耗尽 | ❌ 否 | `Harness execution failed …: [Errno 24]` |
| C_llm_api_5xx | 模型 API 5xx | ❌ 否（供应商侧） | `Unknown Error in LLM interaction: RetryError[… InternalServerError]` |
| D_agent_side:* | agent/判分真实失败 | ✅ 是 | 其余（test_timeout / agent_timeout / parse_error / unset） |

**强制口径**：
1. 原口径（全部判定）与归因后口径（agent 可比集）**必须并列**，禁止只报一个。
2. 环境类失败占失败比 >30% → 基线标"不可用基线"。
3. **`failure_mode` 字段对已解决任务也被填充**（实测：7 例 resolved 中 3 例 `agent_timeout`、4 例 `unset`）→ 失败分布必须以 `is_resolved` 为准，不得用 `failure_mode` 分布冒充失败分布。
4. token 字段大面积缺失时（区分 **null** 与 **0**：null = 未回填，0 = 已计费为零），**成本标"不可用"**，**不得把 null 当 0、也不得把 0 当"零成本"**（D8）。本基线实例：nonzero 18 / zero 9 / null 52。

复算：

```bash
python3 eval/rules/attribute.py \
  --run-dir eval/results/<scope>/<ts> --log eval/logs/<log>.log
```

---

## 4. 报告模板（固定字段，缺一即不合格）

```
scope / run_id / 提交 SHA
模型档位 / provider / 温度 / K / 每轮 token 上限
数据集版本 + 题面 sha256（外部基准必填）
样本量 n（每臂）
pass@1 / pass@K / Wilson 95% CI
Δpass@1（带符号）/ Δpass@K / Δtokens
失败归因表（含 unknown_agent_error 拆解到子类）
证据等级 A/B/C
成本：tokens / 费用 / 时长 / 轮数（不可用时显式声明）
insufficient 字段
provider 列表 + 单 provider 时的"不可外推"标注
```
