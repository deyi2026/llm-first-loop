# S1 冻结包规格：gold / filler 阳性-阴性对照

- 日期：2026-10-19
- 依据：`docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md` §10.2 / §10.3 / §10.5；`s0_p28/GATE-AMENDMENT-v2.md` §4（D2 前置 3）
- 状态：冻结前草案（sha256 由 `CALIBRATION-FREEZE-s1.json` 绑定）

## 1 目的

S1 只回答两个问题，不回答“卡有没有用”：

1. **阳性对照**：人工写的显式 gold 卡能否让 S0 v1.3 的四条机械 check 在卡依赖集合 D 中翻动？翻不动 → 仪器测不到目标行为，禁止进 S2。
2. **阴性对照**：等长、同结构、内容无关的 filler 卡是否会让任何实例由 fail 翻 pass？翻 ≥1 → check 测的不是目标行为，停。

## 2 臂与样本

- 臂：`gold_card`、`filler_card`；每臂对 `s0_p28/pool_p28.jsonl` 的 120 个实例各调用 1 次（一题一调用，rep=1）。
- 卡：`cards/gold.md`、`cards/filler.md`，全文经 `run_s0.build_prompt` 注入 `<method_card>`（同一 `PROMPT_TMPL`、`SOLVER_RULES`、回执夹具，`PROMPT_VERSION=p2`）。调用复用 `run_s0.ask`（`max_tokens=8000` 起、`finish=length`/empty content 时 1.6x 升级），与 S0 逐字一致。
- 不重跑 `no_card`：基线继承 S0 的 `no_card` 120 条（同模型、同 prompt、同题、同夹具；S0 `calls.jsonl` sha256 冻结在 `CALIBRATION-FREEZE-s1.json`）。`orig_card` 只用于定义 D，不参与 S1 判定。
- D 集合：S0 v1.3 下 `case_pass(no_card,i)=False` 且 `case_pass(orig_card,i)=True` 的实例集合，现算；S0 终值 D=28（`results/analysis_s0.json`）。

## 3 判分

- 判分器：`run_s0.GRADERS["v1.3"]`（c1–c4 机械 check），逐字复用，不重写。
- `case_pass(i)`：4 条 check 全 True 且非 `void`；`void` 仅空文本，4 check 为 None → `case_pass=False`（与 S0 一致）。
- 不使用 LLM judge，不做人工改判。

## 4 门槛（冻结，事后不得改）

### 4.1 gold

- **G1（实例级）**：`|{i ∈ D : gold_pass(i)=True}| ≥ 2`。
- **G2（check 级）**：在 D 的实例上，`no_card` 为 False 而 `gold` 为 True 的 check 种类数 `≥ 2`（c1–c4 去重）。
- G1 与 G2 同时满足 → gold 通过；任一不满足 → **仪器不合格，禁止进 S2**，回 S0 修 check（T4）。

### 4.2 filler

- **F1（阴性）**：全体 120 个实例中，`no_card_pass(i)=False` 且 `filler_pass(i)=True` 的实例数 `= 0`。
- F1 不满足（≥1）→ **停**，判定 check 测的不是目标行为，回修 check。
- filler 在 `no_card_pass=True` 的实例上翻 fail 不触发 F1，但必须报告（描述性）。

### 4.3 数据完整性（前置）

- 每臂 120 行 `ok`，`key` 无重复，`prompt_version` 全 `p2`，`card_sha256` 与冻结值一致。
- 若某臂某实例缺失：剔除并报告；若剔除使 G1/G2/F1 的判定改变，判 `INCOMPLETE`，补跑后再判。
- `void` 行计入 `case_pass=False`，不剔除；报告 void 数。

## 5 报告口径

- 主表：per-arm `case_pass`、rate、Wilson 95% CI；gold/filler 对 no_card 的 McNemar exact p（仅描述性，不作门槛）。
- 明细：D 的 28 个实例逐条 `no_card / gold / filler` 的 c1–c4 与 case_pass；G2 的翻转 check 列表。
- 必须并列 S0 v1.3 的 D=28、R=16、McNemar p=0.096，避免把 S1 的通过误读为“orig 卡有效”。

## 6 冻结与污染检查

- **等长**：gold 744 字符 / filler 719 字符（差 3.36%）；CJK 388 / 356；UTF-8 1638 / 1519。以字符数作为 token 的确定性代理（同语言、同 Markdown 结构），差 <10%。
- **同结构**：两卡均为 frontmatter + Trigger / Discriminator / Short path / Stop conditions / Verification / Counterexamples 六节。
- **内容无关**：filler 的决策场景是 CSV 批量导入前的 schema 校验，不包含链接内容判定、澄清提问、互斥选项、昂贵动作宣称等目标行为。
- **近重**：两卡正文与 `pool_p28.jsonl` 每个 question 的 8-gram 重合率必须 ≤0.3（question 为 URL，预期 0）。
- **不自引**：两卡不得出现实例 URL、标题、S0 回复原文或答案措辞；发布前 lint + 人工逐条过一遍（审查记录附后）。
- **一题一调用**：满足 §10.3-2；无 batch 内位置效应。

## 7 运行

```
python3 evals/methodcard_rsi_v1/s1_gold_filler/run_s1.py --threads 2
python3 evals/methodcard_rsi_v1/s1_gold_filler/analyze_s1.py
```

`run_s1.py` 启动时校验 `CALIBRATION-FREEZE-s1.json` 内的卡/脚本 sha256；不一致即退出，不自动改冻结。

## 8 解释边界

- S1 PASS 只证明“v1.3 check 可被显式规则卡翻动、且不被无关卡翻动”，不证明 orig 卡有正效应。orig 卡的效应仍由 S0 的 D/R 描述，S2 才做接受判定。
- S1 FAIL 不推翻 S0 的 D=28；只说明该仪器不能用于 S2 的接受判定。
