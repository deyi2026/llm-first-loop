# DPE 资格判定规格 v2（dpe_spec_v2.md）

- 状态：**DRAFT-PREPREREGISTRATION**。在 δ_min / α / 目标功效 / 样本量 / CI 方法 / 成本上限经开发集估计并由**人工预注册冻结**之前，本文件不构成任何门槛；全部待冻结参数以 `⟨TO-PREREGISTER⟩` 占位，**任何位置不得凭空填数**。
- 版本：v2-draft（2026-11-16，Asia/Shanghai）；冻结后改标 v2-frozen 并登记冻结哈希三件套（预注册 / 冻结 / 结果互指）。
- 配套：`docs/DESIGN-20261115-knowledge-self-improvement-loop-v1.md`（内部 v1.3.1）R2/§4.2；Goal GOAL-20261116-f0858d99（TASK-f0858d99-009 = Q-02 / TASK-f0858d99-010 = Q-03）。
- 依据：第一 Run 只读调查 A 报告（2026-11-16）＋第二阶段执行指令（2026-11-16 01:27）。本文件内全部历史数字为 2026-11-16 在 origin/main@9e6b438c 工作树的**本轮实测**（与 root checkout 指纹一致，见附录）。
- 零触碰声明：`dpe_spec.md`、`d_sets.json`、`review_pack.csv`、`score.py` 与 S0/S1/S1b 全部冻结材料**保持原样**；本目录仅新增本文件，历史口径不作追溯性修改。

## 1. 历史口径对账（Q-02：三处不一致的定性与真值裁定）

| 口径 | 来源 | 本轮实测 | 定性 | v2 裁定 |
|---|---|---|---|---|
| 31 实例 / 93 条（=31×3 臂） | `dpe_spec.md:36` | d_sets 中不存在 31 | 规划期写作口径，未随数据落地更新 | **作废**（仅存历史），不据此发盲标 |
| v1.3_D / v1.4_D / union | `d_sets.json` | 28 / 30 / union 46 实例（三个列表长度；union 46 × 3 臂 = **138 条记录**口径，与旧 93=31×3 同构） | 实际 D 集合底册 | **实例集真值**：资格判定实例集 = 冻结 d_sets 的 union（或预注册时点重取的 D 集合，须绑定该 json 的 sha256） |
| 60 条 = 20 实例 × 3 臂 | `review_pack.csv` | 60 条 / 20 实例；P1–P5 标注列全空（各 60 条）；物理行 684 行（text 字段含换行，行数≠记录数） | 已生成的盲标工作包（预填 P1/P4/P5，人工标注列未标） | **工作底稿**：用于组织盲标流程，不定义实例集；若与冻结实例集不一致，须按冻结实例集重新生成并绑定 sha256 |

不一致根因：spec 写作（预期 31）偏离 d_sets 落地（28/30/46），pack 又按当时可得实例子集（20 实例）生成——三者用途不同但从未互相对账。**v2 起规则：实例集唯一真值 = 冻结的 d_sets（或其预注册替代）；spec 文本、pack 生成、统计报告三处数字必须同源，发现分叉即规格违规，先对账再标注。**

## 2. 资格判定规则（Q-03）

### 2.1 停止规则（替代 `dpe_spec.md:49` 的单轮规则）
- κ < 0.60（Cohen's kappa，双人原始独立标签，阈值沿用既有）⇒ 允许**规格修订 #1** 并重标（登记修订 diff、理由、重标范围）。
- 修订 #1 后仍 κ < 0.60 ⇒ 允许**规格修订 #2** 并重标。
- 修订 #2 后仍 κ < 0.60 ⇒ **计划性 STOP**：`instrument_status=unqualified`、`effect_verdict=not_assessed`，**禁止第三次修订**（防口径/数值修补到过）；只出诊断报告。STOP 后重启须人工新裁决（新预注册），不得沿用旧账续标。

### 2.2 同回复重测（判分器信度 ≠ 求解器随机性）
- 同一批**冻结回复**跨判分器/标注轮的一致率 ≥ 0.8（沿用 v1.3 Q3 裁决）；不同采样批次的 gold 回复单独报告求解器稳定性，不得混作判分器重测信度。

### 2.3 语义变形（两类分开，先人标金标）
- 语义不变扰动：判分标签**不得翻转**；语义改变注入：按人工金标**正确跟随**。两类分别计数与报告，不合并为单一通过率。

### 2.4 仪器/效应双轴
- `instrument_status ∈ {not_run, qualified, unqualified}`；`effect_verdict ∈ {benefit, regression, inconclusive, not_assessed}`。
- 仪器不合格 / 确认集不独立 / 功效不足 ⇒ `not_assessed`（并列原因），禁止伪装为 `inconclusive` 或“未测出”。

### 2.5 独立新确认集（防同源泄漏）
- 现有数据**不存在题族字段** ⇒ 分组去重改用 normalized URL / session / cluster 等可得字段，并在 manifest 声明替代口径与局限。
- 确认集与开发材料（S0/S1/S1b 120 题、D 集合、盲标用例）**分组互斥**；冻结 manifest 含去重摘要与“未参与调参”声明。

### 2.6 预注册统计（仅确认集；McNemar 升格）
- 旧 `s1_gold_filler/S1-SPEC.md:49` 的 McNemar exact p 为“仅描述性、不作门槛”——该口径对 S1 历史结果**不追溯变更**。
- v2 确认集：双侧精确 McNemar 与配对差 CI 为**预注册门槛检验**（CI 方法预注册）；配对净效应 Δ=(b−c)/n；**开发集上的一切检验一律描述性**。

## 3. 预注册流程（防凭空填数）

1. **开发集估计**：以冻结 D 集合 + S0 历史分布估计配对不一致率、δ_min 候选范围、成本曲线；产物落 `dpe/estimates/`（脚本 + 输出双留痕）。
2. **人工预注册冻结**：δ_min、α、目标功效、样本量 n、CI 方法、多重比较处理、成本上限，由人工确认后写入 `dpe/PREREG-V2.json` 并冻结哈希。
3. 三件套互指（预注册 / 冻结 / 结果）完成后，才允许确认集运行与确认性统计。
4. 当前占位（**一律不得填数**）：δ_min=⟨TO-PREREGISTER⟩；α=⟨TO-PREREGISTER⟩；目标功效=⟨TO-PREREGISTER⟩；n=⟨TO-PREREGISTER⟩；CI=⟨TO-PREREGISTER⟩；成本上限=⟨TO-PREREGISTER⟩；多重比较=⟨TO-PREREGISTER⟩。既有沿用项（非本轮新造）：κ 门槛 0.60、盲标 raw agreement ≥ 0.85、同回复一致率 ≥ 0.8、S1b 两项预注册诊断（注入测试、跨批一致率 ≥ 0.8）。

## 4. 本文件自身验收（本 Run 内）
- 本 lane 的 git 变更**只含本文件**：`git diff --name-only origin/main..HEAD` 输出仅为 `evals/methodcard_rsi_v1/dpe/dpe_spec_v2.md`。
- Markdown fence 平衡；除本轮实测数字与既有沿用阈值外无任何新数字，其余参数全部为占位符。
- 历史文件 sha256 与附录一致；未运行任何 Provider 评测、未做盲标、未合并 / 未推送（第二 Run 禁令）。

## 附录 历史文件指纹（2026-11-16 本轮实测；origin/main@9e6b438c 工作树与 root checkout 逐字节一致）

- `d_sets.json` sha256=26cb292d336ab953102f20ea856865226ddeaaf313c8718bfc5c38fd6dd6a4b9
- `dpe_spec.md` sha256=ffc60b5f8b387ca5ffda8e9717cf77f829c7afeb26b715f283d97f609eb128a3
- `review_pack.csv` sha256=6421fc139f20ce494a991e867d7d39de58b0130f01d2f60c82c343260bbaefcd
- `score.py` sha256=fc93ede226e39d8a62963f1c8d24ab03d55ce100195b854510e4ec060140e14c
- `s1_gold_filler/S1-SPEC.md` sha256=da91169080f8d71364b0be6fed5019d2a80d79eadf3b2b280b04e72e68d21245
