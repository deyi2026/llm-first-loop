# ASSESS: S1.5a 题库存量第一轮筛（零新增调用）

- 日期：2026-10-21 ｜ 状态：完成 ｜ 触发：用户批准"先筛一轮看存量"
- 上游：`docs/DESIGN-20261021-prefilter-and-ablation-before-s2.md` §S1.5a
- 判据（逐字取自上游）：逐题 no_card 通过率 ∈ [0.3, 0.6]，`P_new` ≥ 120 题
- 结论：**两条候选线均不足，且暴露一个比题库数量更硬的结构性阻断**

## 0. 执行摘要

| 候选线 | 现有题量 | 池级 no_card | 逐题落 [0.3,0.6] | k=5 重测估计 | 距 120 |
|---|---|---|---|---|---|
| A `heldout_v2.jsonl`（合成题） | 33 | — | **4** | 未测（n=1~3 粗测） | −116 |
| B `s0_p28/pool_p28.jsonl`（真实实例） | 120 | **0.350** ✓ | **19**（单次口径） | **40.8**（95%CI 31–51） | −79 |
| A+B 合并 | 153 | — | 23 | 约 45 | **−75** |

**判定：`LIBRARY_ABLATION_BLOCKED_ON_ITEM_DIFFICULTY`**（上游预注册标签）。

**但真正的阻断不在题量**：S1.5b 要在 41 张在用卡上做配对，而现有真实语料只能为其中 0 张提供 ≥10 个触发实例（详见 §4）。唯一拥有 120 实例池的 P28，不在 41 张在用卡之列，且其单卡消融 S0 已跑过——方向为正（no_card 0.350 → orig_card 0.450，+10pp）但功效不足、未达显著（p=0.0961），不是零效应。

## 1. 方法与数据源

本轮**未发起任何模型调用**。全部结论由已冻结的既有数据离线重算：

| 数据源 | sha256 / 冻结 | 说明 |
|---|---|---|
| `evals/methodcard_rsi_v1/calibration_v4.json` | 与 `CALIBRATION-FREEZE-v4.json` 对应 `5de7f799…` | 33 题 no_card check 级通过率，probe 口径为 `batch_solve_prompt([case], None)`＝不给卡 |
| `evals/methodcard_rsi_v1/s0_p28/results/calls.jsonl` | `bf0aec40…`（analysis_s0.md 记录） | 120 实例 × no_card 臂原始回复，240 调用中 ok=240 |
| 判分 | `run_s0.GRADERS['v1.3']` | 与 `analysis_s0.md` 逐字同源，纯正则、无 LLM judge |
| `data/methods/usage.jsonl` | 54 行 / 42 distinct ref | 在用卡口径 |

重算的 no_card 池级值与 `analysis_s0.md` 第 26 行一致（42/120＝0.3500），判分链可复核。

## 2. 结果 A：heldout_v2（33 题）

`rate` 分布（check 级，n=1~3）：

| no_card 通过率 | 题数 | 题号 |
|---|---|---|
| 1.000（饱和） | 17 | H03/H05–H14/H16–H20/H32 |
| 0.750–0.857 | 6 | H01(0.750)/H33(0.750)/H28(0.800)/H31(0.800)/H24(0.833)/H23(0.857) |
| 0.667 | 6 | H02/H04/H25/H29/H30/H34 |
| **0.500–0.571 → 目标带** | **4** | **H15(0.500,n=3), H26(0.500,n=1), H27(0.500,n=1), H35(0.571,n=1)** |

合计 17+6+6+4 = 33，与 `cases` 总数一致。

- 落在目标带 **4 题**，距 120 缺 116。
- 沿用现有 `usable` 宽带上界 0.8 时为 14 题——即使按宽口径也只有 14。
- 该 4 题中 3 题 n=1，是单次采样，不能作为 `P_new` 定稿；但即便全部确认，上限仍是 4。
- 17/33 题 no_card 满通过，印证 v1 的 94.1% 饱和记录（`README.md` 第 40 行）：此库作为难度来源已耗尽。

## 3. 结果 B：pool_p28（120 实例）

### 3.1 池级达标，逐题不达标

v1.3 no_card：case_pass（4 check 全过）**42/120 = 0.3500**，Wilson 95% [0.2705, 0.4388]——正落在 [0.3, 0.6] 内。就此池**作为整体**而言，S1.5a 的"压到 0.3–0.6"目的已达成。

但 S1.5a 是**逐题**筛。按实例重算 check 通过数（满分 4）：

| check 通过 | 题率 | 实例数 |
|---|---|---|
| 1/4 | 0.25 | 1 |
| **2/4** | **0.50 → 目标带** | **19** |
| 3/4 | 0.75 | 58 |
| 4/4 | 1.00 | 42 |

逐题命中率 19/120 = **15.8%**。目标带内的 19 个实例：P28-003/018/020/026/033/040/041/052/054/057/060/061/065/066/073/077/089/090/101。

### 3.2 若真做 k=5 重测

单次采样的 0/4–4/4 只是粗估。以 Beta(1+k, 1+4−k) 作真实通过率后验，模拟 k=5 重采并保留 2/5 或 3/5（即 0.4、0.6，均为带内可取值），20000 次：

- 保留题数 **均值 40.8，95%CI [31, 51]**（seed 20261021）
- 要达到 120 题，按此命中率需候选池 **≈353 个实例**

现有池 120 个，缺口约 233。而 P28 语料中独立实例上限为 109（`TRIGGERMATCH-20261019.md` 第 59 行：110 条 / 85 会话 → 109 独立），**已挖尽**。扩库不可能在 P28 语料内完成。

> 注：§3.2 是模拟估计，非实测。它只用于确定扩库规模量级，不得作为 `P_new` 结论。

## 4. 结果 C：结构性阻断（本轮筛暴露，比题量更硬）

### 4.1 两个集合不相交

| 集合 | 规模 | 触发实例供给 |
|---|---|---|
| S1.5b 对象：`usage.jsonl` 在用卡 | 42 distinct ref（41 有 episode_ref） | 每卡独立 episode **1–3 个**，合计 52 |
| 有实例池的卡 | P28（120 实例）、P23（2 实例） | — |

- P28 的 method_ref 为 `method:instructionless-content-drop-clarify-via-canonical-register-1c05c71f5acb`，`status: candidate`，**不在 usage.jsonl 任何一行**（零使用记录），目录下仅 `METHOD.md`。
- 因此在用卡 ∩ 有实例池的卡 = **空集**。

### 4.2 算术冲突

S1.5b 设计：41 卡 × 每卡 10 题 × 2 臂 = 820 调用，McNemar 配对。
实际可配：41 卡共 52 个独立 episode，**每卡 1–3 个**；且 R13 规定"同一任务、同一陷阱的多个会话只算 1 个独立实例"，多数卡实际只有 **1** 个可用配对。

单实例无法构成 McNemar 的 2×2 表，无法出 p 值与 Δ。**S1.5b 按现设计不可执行。**

### 4.3 更根本的：S1.5a 修错了层

`TRIGGERMATCH-20261019.md` 第 11 行：5 卡 × 33 题 = 165 对，`direct` 判定 **165/165 为 none**。即这些题根本不触发这些卡——不是题太简单，是 cue/temptation/action/stop 四元组不匹配。

M0 主跑的 Δ=0.000 因此有两层成因：

1. 天花板（题太简单，给不给卡都过）——S1.5a 试图修这一层；
2. **不相关**（题不触发卡，卡无施展空间）——S1.5a 修不了。

只修第 1 层，即使凑到 120 题落在 [0.3,0.6]，若这些题仍不触发目标卡，Δ 依旧为 0。**难度与相关性是两个独立条件，S1.5a 只覆盖前者。**

## 5. 判定

| 项 | 结论 |
|---|---|
| `P_new` 存量（合并 A+B，k=5 口径） | 约 45 题（A 侧 4 题未经 k=5，B 侧 40.8 为模拟） |
| 是否达 120 | **否**，缺约 75 |
| 上游失败标签 | **`LIBRARY_ABLATION_BLOCKED_ON_ITEM_DIFFICULTY`** 成立 |
| 附加结构标签 | **`BLOCKED_ON_TRIGGER_INSTANCE_SCARCITY`**：41 张在用卡无可用触发实例池 |
| S1.5b 可执行性 | **按现设计不可执行**（配对单元不足，非样本量不足） |
| 扩库性质 | 不能靠造合成题解决；需真实使用中积累触发实例，属时间资产 |

## 6. 建议的三个方向

**方向 1（推荐）：停止 41 卡计划，改立"实例池建设"为独立工作线。**
在真实使用中为高价值卡按 R13 四元组标注触发实例，每卡 ≥10 个独立实例后再启动消融。本季度内不应期待 S1.5b 出结论——这是资产积累，不是调用预算问题。

**方向 2（并行，无阻断）：先做不需要配对实例的部分。**
S1.5c 结构预筛（纯文本、零成本、仅排序）；以及 DESIGN §5 已采纳的"可执行组件优先"——把散文卡改造为 skills/scripts。这条路径不需要证明"卡有没有用"就能推进，且论文消融显示它贡献高于 prompt 侧。

**方向 3（若坚持要实验）：P28 单卡有正向信号，但语料内功效不足，不要重做。**
S0 在 120 实例上 v1.3：no_card case_pass 0.350 → orig_card 0.450（**+10pp**），D=28 / R=16，精确 p=0.0961。这是**方向为正、未达显著**，与 M0 的 Δ=0.000 性质不同。

但保持该效应量（discordant 率 0.3667、D 占 discordant 的 0.636）达 p<0.05 需 **n=152**；P28 独立实例上限 109（现有 120 已含非独立会话，`TRIGGERMATCH` 记录 110 条 / 85 会话 → 109 独立）。**差约 43 个独立实例，语料内补不齐。** check v1.3 已冻结、承诺不回调。

即：不是"重跑一次就能变显著"，而是当前语料下功效约差 30%。

## 7. 复现命令

```bash
cd evals/methodcard_rsi_v1
# A 线：heldout_v2 目标带题数
python3 -c "import json;d=json.load(open('calibration_v4.json'));print([k for k,v in d['cases'].items() if 0.3<=v['rate']<=0.6])"
# B 线：pool_p28 逐题 check 通过数分布
cd s0_p28 && python3 -c "
import json,sys,collections;sys.path.insert(0,'.');import run_s0 as R
rows=R.dedupe([json.loads(l) for l in open('results/calls.jsonl')])
nc=[r for r in rows if r.get('arm')=='no_card' and r.get('ok')]
g=R.GRADERS['v1.3']
print(collections.Counter(sum(1 for v in g(r['text'])[0].values() if v) for r in nc))"
# C 线：在用卡实例数
cd ../../.. && python3 -c "
import json,collections;rows=[json.loads(l) for l in open('data/methods/usage.jsonl')]
by=collections.defaultdict(set)
[by[r['method_ref']].add(r.get('episode_ref')) for r in rows if r.get('episode_ref')]
print(collections.Counter(len(v) for v in by.values()))"
```
