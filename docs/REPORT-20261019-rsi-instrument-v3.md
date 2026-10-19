# REPORT-20261019：方法卡 RSI 的仪器化（R0–R3 执行结果）

**状态**：R0 完成 / R1 完成（结论=不合格，冻结被拒）/ R2 完成 / R3 有 MVP+1 个真样本，未做量化
**模型**：glm-5.3-flash（端点未变，与 v2 同模型，可对比）
**数据**：`evals/methodcard_rsi_v1/results_v3_baseline/calls.jsonl`（54 次有效调用 / 55 次）
**题集**：`heldout_v1.jsonl`，20 题 × 55 条 check，sha256 见 `summary.json`

---

## 1. 结论（先看这 5 条）

1. **这套题已经饱和**：不给卡，check 级通过率 batch 143/152=**94.1%**、single 105/110=**95.5%**。
   55 条 check 里 **50 条从不失败**，只有 5 条（9%）有翻转空间。
2. **温度 0 下的重复调用不产生信息**：batch 口径 3 次重复的逐 check 结果**逐位相同**（5 个族全一致）。
   继续跑 3 repeats 是花 3 倍钱买 0 信息。
3. **batch 与 single 不是等价口径**：H02 从 0.667(batch) 变 1.0(single)，H03 从 1.0 变 0.833。
   以前用 batch 当"主口径"会系统性扭曲结果；单题调用才该是主口径。
4. **闸门 v3 已可证伪，但它今天只会返回 REFUSE**：标定 4/20 可用，B/C/E 三族 0 可用。
   这不是闸门失败，是闸门正确地拒绝了没有分辨力的仪器。
5. **模板算子的退化被坐实**：22 张变异卡里 **22 张**含同一句「Verification 未逐条通过前不结案（覆盖全部 N 条验证条目）」，
   只有 N 取 1/2/3/4 的区别——4 个字符串变体，内容零差异。新写的内容级算子（LLM 定向改写 + 规则校验）在 1 个真卡上产出**过校验且内容相关**的 patch（n=1，未量化）。

---

## 2. 可复现命令

```bash
cd evals/methodcard_rsi_v1
python3 baseline_nocard.py --mode batch  --repeats 3   # 15 次调用，族内 4 题一批
python3 baseline_nocard.py --mode single --repeats 2   # 40 次调用，每次 1 题
python3 calibrate_v3.py [--freeze]                     # 标定；不达标时 --freeze 返回 2
python3 gate_v3.py --selftest                          # 闸门逻辑 9/9（离线，无模型调用）
python3 analyze_prereg_v3.py --demo                    # 4 臂接线；当前标定 → REFUSE
```

---

## 3. 基线分布（check 级）

| 族 | 题 | batch 率 | single 率 | 可用 |
|---|---|---|---|---|
| A_effectiveness | H01–H04 | .75 / .667 / 1.0 / .667 | .875 / 1.0 / .833 / .667 | 3 |
| B_completion_gate | H05–H08 | 1.0 ×4 | 1.0 ×4 | 0 |
| C_authority | H09–H12 | 1.0 ×4 | 1.0 ×4 | 0 |
| D_patch_verify | H13–H16 | 1.0/1.0/**0.5**/1.0 | 1.0/1.0/0.75/1.0 | 1 |
| E_dedupe | H17–H20 | 1.0 ×4 | 1.0 ×4 | 0 |

可用的 5 条 check：`H01/c2`、`H02/c3`、`H03/c1`、`H04/c1`、`H15/c1`。
**推论**：一个"完美变异器"（把这 5 条全翻过来）的 mean Δ=+8.75pp，CI95=[+2.5,+16.3]；
翻 1–2 条的现实变异器 Δ≈2–3pp，CI 必然跨 0 → 裁决只能是 `NO_SEPARATION`。
**这套题只能识别"满分改进"，识别不了"小改进"**——而小改进才是方法卡该有的量级。

---

## 4. 四个仪器事实（都是这次跑出来的，不是推测）

**(a) max_tokens 被 reasoning 吃满 → 数据点消失。**
`A_effectiveness|r2` 首次以 `empty content finish=length` 失败，被记成一次失败调用。
`H.call` 把"预算不够"抛成 RuntimeError，上层没接住，等于**按题目难度系统性丢样本**。
已修：`ask()` 捕获 length/empty 并倍升预算（6000→12000→24000）后重跑；`method_mutator_llm.call_llm` 同样处理。
丢的那 1 次没有补跑（A 族 r1/r3 逐 check 已完全一致，补跑不改变结论）。

**(b) 确定性。**
batch 口径 15 次调用覆盖 5 族，逐 check 位串完全一致（例如 B 族三次都是 `1111 11 111 11`）。
single 口径 40 次里只有 3 次翻转（H01 r2、H03 r2、H15 r2）。

**(c) 口径效应。**
同一题、同一模型，batch 与 single 的 check 率差最大 0.333（H02）。原因是批内 4 题互相提供格式线索。
结论：**单题调用为主口径**；batch 只用于与 v2 历史值对齐。

**(d) 题型偏置。**
C_authority（该拒绝就拒绝）与 E_dedupe（重复即删）在无卡状态下 100% 通过——
这两族测的是模型的默认行为倾向，不是"卡有没有帮上忙"。这是题型设计问题，不是模型太强。

---

## 5. R1 标定结论

`calibration_v3.json`：`usable_total=4`，`calibration_ok=false`，`need_new_cases=[B,C,E,D]`。
`--freeze` 按设计拒绝（退出码 2），不产出 `CALIBRATION-FREEZE.json`。
**因此今天不可能签署 v3 预注册**——题集都不合格，签了也是空协议。

补题的硬标准（写进下一版预注册）：
- 每题无卡 check 率落在 **0.30–0.80**；同族 ≥2 题；
- 来源必须是**真实失败**（`exception_log`/`self_correction_log`/lesson 卡反推），不造人造题；
- 新题入库前先跑 1 次无卡基线，不达标不入库。

---

## 6. R2 闸门 v3

五道门：G-1 标定前置（REFUSE）→ G-2 完整性（frontmatter/violation）→ G-3 安慰剂（无关卡 |Δ|≤0.05）→
G-4 有害对照（必须测出 Δ<-0.05）→ G-5 功效（CI 宽 ≤0.20）→ G-6 裁决（SHIP/REJECT/INCONCLUSIVE）。
阈值集中在 `gate_v3.py` 顶部常量，预注册引用同一份，避免"判据写两处"。

验证（都是机械可复算的）：
- `gate_v3.py --selftest` → **9/9**，覆盖 SHIP / REJECT / PLACEBO_LEAK / HARM_UNDETECTED / LOW_POWER / COST_NOT_MET / PROTOCOL_VIOLATION / CALIBRATION_INSUFFICIENT。
- 接线：当前标定 + 4 臂演示报告 → `REFUSE(CALIBRATION_INSUFFICIENT)`；
  把标定改成 20 题可用 → `SHIP`（placebo 0、harm −0.5、token_ratio 0.95）。

**未验证**：真实 4 臂实验一次都没跑过。闸门的"能对给定输入给出正确三态"已验证；"能筛出好变异器"未验证。

---

## 7. R3 内容级算子

模板退化的量化证据：`results_v2/mutator/P*/**/METHOD.md` 共 22 张，**22 张全部**含同一句停机条件；
按 N 分 4 个变体：N=3 ×8、N=1 ×8、N=2 ×5、N=4 ×1。句子结构完全一致，只有计数不同。

新模块 `scripts/method_mutator_llm.py`：LLM 只写"这一行怎么改"，规则只管"是不是编的/越界的"。
校验 8 类：SECTION_NOT_ALLOWED / LINE_MISMATCH / MULTILINE / NO_CHANGE / PLACEHOLDER / HEADING / NEW_FACT / SCHEMA。
`--selftest` 9/9（离线）。校验失败**不回退模板**——回退正是 v2 出现 21/22 同句的机制。

真样本（1 个）：对 `absence-claim-probe-by-term-decomposition` 的 `unlinked_verification` 缺陷，
第 1 次尝试即过校验，产出把该卡 Verification 两条判据（file:line 逐点映射、权威 SoT）绑进停手条件的单行 patch。
**限制**：n=1、单一缺陷类型、未测行为 Δ、未测 yield（多卡批量下的通过率）。

---

## 8. 下一步（按顺序，不再并跑）

1. **补题（阻塞项）**：从真实失败里造 B/C/D/E 各 ≥2 题；每题先跑无卡基线验 0.30–0.80。
2. **口径统一**：single 为主，repeats=1；省下的预算用于加题。
3. **量化 R3 yield**：对 20 张有缺陷的卡跑算子，统计"过校验/回退/弃权"比例与平均尝试次数。
4. **首轮 4 臂实验**：只在新的可用题上跑，pairs 数按 CI 宽 ≤0.20 反推（保守 ≥20 对）。
5. **签 v3**：题集 hash + 标定 + 闸门常量 + 算子清单 + 预算上限，一次签完。

---

## 9. 未验证 / 风险

- 5 条可翻 check 集中在 4 题，单条 check 的设计缺陷会被放大成"方法卡有效/无效"的结论。
- single 口径的 3 次翻转说明存在采样噪声；阈值 0.30–0.80 与 0.34 分歧线都是启发式，未做敏感性分析。
- 本报告只测了"不给卡"基线，没有跑任何变异器对卡片的真实影响。
