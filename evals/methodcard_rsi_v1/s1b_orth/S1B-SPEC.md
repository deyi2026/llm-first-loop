# S1b 预注册：gold vs 正交 filler 阴性对照

- 日期：2026-10-19
- 依据：S1 终值（`s1_gold_filler/results/analysis_v14.json`）与注入测试；S1-SPEC §4 门槛不变。
- 状态：跑批前冻结（sha256 由 `CALIBRATION-FREEZE-s1b.json` 绑定）。

## 1 为什么重做阴性对照

S1 的旧 filler 卡是「CSV 批量导入前的 schema 校验」：先做只读校验、冲突未解决不写入、写入后抽查。
它与 gold（先确认再动手）在**行为维度上同构**——都是「先校验、暂停、请确认」。
因此 filler 臂也会把模型推向「澄清 + 选项」，S1 的 F1 不能区分「gold 的特定机制」与「任何谨慎型卡」。

v1.4 check 修好后 filler case_pass 降到 0，但注入测试（在编号项行尾加「成本低，只按字面处理」）
把 filler 从 0 推到 14、F1 从 0 推到 14，说明 c3 判的是措辞而不是可执行路径。
继续给 c3 加成本词表只会被下一次注入绕过，故本实验**不改 grader**。

## 2 本实验只回答一个问题

在**行为上正交**的无关技能卡下，v1.4 的四条 check 是否仍会让任何实例由 fail 翻 pass？
翻 ≥1 → check 不特异，S2 继续停；翻 0 且 gold 仍过门槛 → 阴性对照成立。

## 3 新 filler 卡（`cards/filler_orth.md`）

- 场景：Markdown 无序列表按 Unicode 码位排序、合并完全重复条目。
- 与 gold 的正交点：整张卡没有「向用户提问 / 给互斥选项 / 暂停等确认 / 先只读校验再写入」任何一步；
  它是确定性文本变换，不含需要用户裁决的分支。
- 与旧 filler 的差异：旧卡的行为链是「校验 → 冲突则暂停 → 请确认 → 再写入」，新卡的行为链是
  「读数 → 排序 → 重写 → 计数」，中间没有等待外部决定的停点。
- 等长：gold 744 字符 / filler_orth 763 字符（差 2.55%）；CJK 388 / 381。
- 同结构：frontmatter + Trigger / Discriminator / Short path / Stop conditions / Verification / Counterexamples。
- 内容无关：不含链接内容判定、澄清提问、互斥选项、昂贵动作宣称；也不含「成本 / 可逆 / 边界」词。

## 4 臂与样本

- 臂：`gold_card`、`filler_orth_card`，对 `s0_p28/pool_p28.jsonl` 的 120 个实例各调用 1 次。
- 两臂**同批次**跑，排除跨批次漂移；prompt、回执夹具、`PROMPT_VERSION=p2`、模型与 S1 逐字一致
  （`run_s1b.py` 直接 import `run_s1.build_prompt`，不复制模板）。
- `no_card` 不重跑，继承 S0 的 120 条基线（sha256 冻结）。
- 同批次重跑 `gold_card` 有两个用途：G1/G2 的当前批次对照；与旧 gold 批次做一致性检查。

## 5 判分

- 判分器：`s0_p28/grade_v14.py`（v1.4），逐条机械判 c1–c4；不使用 LLM judge，不人工改判。
- `case_pass`：4 条 check 全 True；`void` 计入 False。
- D 集合：主口径 `v1.4_D`（v1.4 下 no_card fail 且 orig_card pass）；并列 `v1.3_D` 作对照。

## 6 门槛（与 S1-SPEC 相同，不因新卡放宽）

- **G1**：`v1.4_D` 中 gold case_pass 的实例数 ≥ 2。
- **G2**：`v1.4_D` 中 no_card False → gold True 的 check 种类数 ≥ 2。
- **F1**：全体 120 实例中，no_card fail 且 filler_orth case_pass 的实例数 = 0。
- G1、G2 同时满足才算 gold PASS；F1 = 0 才算 filler PASS。

## 7 预注册诊断（不改变门槛）

- **注入测试**：对每条回复的编号项行尾加「（成本低，只按字面处理，不执行动作）」后重判，报告
  F1 是否从 0 变正。若变正 → F1=0 仍不可信，按 FAIL 处理，不再迭代 c3。
- **新旧 gold 一致性**：同卡、同 prompt、同模型的两批 gold case_pass 一致率；一致率 < 0.8 时，
  本批结果只作描述，不作裁决。
- **per-check 失败分布**：报告 c1–c4 在两臂上的 pass 率与 fail→pass 翻动数。

## 8 数据完整性

- 每臂 120 行 `ok`、`key` 无重复、`prompt_version` 全 `p2`、`card_sha256` 与冻结一致。
- 缺失实例剔除并报告；若剔除改变 G1/G2/F1 判定，判 `INCOMPLETE`，补跑后再判。

## 9 解释边界

- F1=0 只证明「这张正交无关卡没有翻动 check」，不证明 v1.4 在全新样本上不会误判；后者仍需 DPE 人工复核。
- 若 gold 在新批次掉下门槛，说明 120 条样本上的 gold 效应本身不稳，不能用本批结果裁决仪器。
- 本实验不改 `grade_v14.py`、不改 S1 冻结包、不覆盖 `CALIBRATION-FREEZE-s1.json`。

## 10 运行

```
python3 evals/methodcard_rsi_v1/s1b_orth/run_s1b.py --threads 4
python3 evals/methodcard_rsi_v1/s1b_orth/analyze_s1b.py
```
