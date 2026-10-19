# REVIEW-S1-CODE — S1 两脚本只读代码审查（bundle + verify 模式）

- 日期：2026-10-19
- 审查对象：`evals/methodcard_rsi_v1/s1_gold_filler/run_s1.py`、`analyze_s1.py`（经 `/tmp/s1_review_bundle.md` 142 行摘录）、`S1-SPEC.md §4`
- 审查方式：只读 bundle + 执行 `python3 /tmp/s1_verify.py`（36 行输出，总 exit 0）。未读两脚本源文件，未读 calls.jsonl。
- 方法论检索：本环境未提供 search_records 工具，按委派"不适用则直接开始"处理。

## VERDICT: PASS（P0=0）

5 项全部通过；2 项子条为证据缺口（bundle 摘录未覆盖对应代码行），无任何证据表明代码存在缺陷，按 P1 记录，不阻塞，建议正式跑前补证。

## 逐项结论

### 1. prompt 等价 — PASS
- 期望：TMPL_EQ=True 且 BUILD_EQ=True（S1 与 S0 逐字可比）。
- 实际（verify §2，exit 0）：`TMPL_EQ True`、`BUILD_EQ True`。
- 佐证（bundle L5-6 注释）：PROMPT_TMPL 与 run_s0 逐字一致（含回执夹具），任何一字改动都会破坏与 S0 no_card 基线（FREEZE.baseline.s0_calls）的配对性。
- 备注：bundle "build_prompt (111-115)" 节摘录实为 load_pool 函数体，build_prompt 本体未直接摘录，本项以 verify 的 BUILD_EQ 为准（见 P1-5）。
- 结论：通过。

### 2. dry-run — PASS
- 期望：exit 0；jobs=240；两卡 sha256 与 FREEZE 一致。
- 实际（verify §1，exit 0）：`model=glm-5.3-flash pool=120 arms=['gold_card','filler_card'] rep=1 jobs=240 pending=240 conc=2`；`freeze 校验通过：.../CALIBRATION-FREEZE-s1.json`；
  - `gold_card   sha256=4c9d22cad90a42378ef917b6ac585119c6d11e01cbf5b2afa6172f147ad4f8a6 chars=744 （与 FREEZE 一致）`
  - `filler_card sha256=2967e0c8e9235f3d247870824875f644ac23bf26870a7d95447967af0c2d439b chars=719 （与 FREEZE 一致）`
- 结论：通过。240 = 120 实例 × 2 臂 × rep=1；dry-run 明示"不调用模型"；两卡 sha 与字符数（744/719，与 spec §6 等长口径一致）均与冻结一致。

### 3. analyze smoke — PASS（仅门槛逻辑）
- 期望：exit 0；G1=28 / G2=3 / F1=0；JSON 与 MD 生成。
- 实际（verify §3，exit 0）：`G1=28 (need >=2)  G2=3 (need >=2)  gold=PASS`；`F1=0 (need ==0)  filler=PASS`；`integrity=OK  verdict=PASS`；`wrote /tmp/s1_smoke/review/analysis_s1.json , /tmp/s1_smoke/review/analysis_s1.md`；`files True True`。
- 结论：通过。**强调：smoke 用 orig 文本当 gold、no_card 文本当 filler 的构造数据，G1=28/G2=3/F1=0 只验证门槛逻辑与产物生成，不是真实实验结果，不得作为 S1 结论引用。**

### 4. FREEZE 完整性 — PASS
- 期望：run_s1 / analyze_s1 / lint 三个 sha_ok 均 True。
- 实际（verify §4）：`run_s1 sha_ok True`、`analyze_s1 sha_ok True`、`lint sha_ok True`。
- 结论：通过。三个脚本与冻结值一致，被审查对象即被冻结对象。

### 5. bundle 代码逐条 — PASS（2 项子条为证据缺口，记 P1）
- 5a job 复用 run_s0.ask — 证实：run_s1.py L168 `r = S0.ask(prompt)`，注释"复用 S0 的 max_tokens=8000 + 1.6x 升级，避免 reasoning 吃空 content"。结构性复用同一函数，8000 起步与 finish/empty 升级语义随 S0.ask 一并继承（参数细节本体在 run_s0，不在 bundle 内，由复用调用 + 注释佐证）。
- 5b 字段完整性 — 证实：L172 成功行落盘 `text/finish/attempts/tokens(=usage.total_tokens)/usage`，另有 key/arm/rep/instance 元数据、latency/model/card_sha256/prompt_chars/prompt_version/created_at；失败路径 L177-180 落 `ok=False` + error 截断 300 字符（成功失败都落盘）。
- 5c G1/G2/F1 与 spec §4 一致 — 证实（逐条对照）：
  - §4.1 G1（D 上 gold case_pass 实例数 ≥2）：L327 在 d_ids 上取 `gold_by[i]["case_pass"]`；L341-342 `g1 >= 2`。一致。
  - §4.1 G2（D 上 no_card False 而 gold True 的 check 种类数，c1–c4 去重，≥2）：L332-333 按 CS 逐 check 比较 `is False`/`is True`；L328/336 `flip_kinds` 集合去重；L341-342 `g2 >= 2`。一致。
  - §4.1 "G1 与 G2 同时满足"：L342 `g1 >= 2 and g2 >= 2`。一致。
  - §4.2 F1（全体实例中 no_card fail 且 filler pass 数 =0）：L345 `common_nf` 取全体交集（未限 D，正确）；L346-350 `f1 == 0`。一致。
  - §4.2 描述性要求（no_card pass 而 filler fail 须报告）：L348-349 `fpf_ids` 已计算（是否写入报告文件不在摘录内，见 P1-4）。
  - §4.3 完整性前置：L353-371 每臂校验 n==expected_n、dup_keys==0、prompt_version==[run_s0.PROMPT_VERSION]、card_sha256==[FREEZE 值]，并校验 s0_calls_sha256；L373-378 integrity 不 ok 先判 INCOMPLETE，优先于 PASS/FAIL。一致。
- 5d D==28 才继续 — **未证实（证据缺口，P1-1）**：bundle 的 analyze 摘录自 L326 起，未含 D 的构造与 `len(D)==28` 硬门禁代码行。间接一致：smoke 输出 G1=28 ⟹ smoke 的 |D|=28（按构造）；但现有证据无法区分"有门禁且通过"与"无门禁"。
- 5e INCOMPLETE 优先 — 证实：L373-378（integrity 先于 gold/filler 判定，见 5c 末条）。
- 5f 复用 v1.3 grader — **未证实（证据缺口，P1-2）**：摘录未含 grader import/调用行（L90 出现 `s1_graded` 仅表明存在分级步骤）。间接一致：smoke 分级跑通并产出合理 check 结果；grader 版本无法从 bundle/verify 输出确认。

## 复现

```
$ python3 /tmp/s1_verify.py        # 工作目录：仓库根；总 exit 0
== 1 dry-run ==            exit 0；jobs=240；gold/filler 两卡 sha 均"（与 FREEZE 一致）"
== 2 prompt equivalence == exit 0；TMPL_EQ True；BUILD_EQ True
== 3 analyze smoke ==      exit 0；G1=28 G2=3 gold=PASS；F1=0 filler=PASS；integrity=OK verdict=PASS；files True True
== 4 FREEZE integrity ==   run_s1 / analyze_s1 / lint sha_ok 均 True
== 5 git status (s1 only)== 8 行，全部 untracked（见 P1-3）
```
bundle：`/tmp/s1_review_bundle.md`（142 行）。

## P1（不阻塞）

1. **D==28 硬门禁证据缺口**：bundle 未含该代码行；建议增补该行（或 verify 加 D≠28 负例断言非零退出）后再放行正式跑。
2. **v1.3 grader 复用证据缺口**：bundle 未含 grader 来源行；建议增补 import/版本断言一行。
3. **S1 目录 8 个文件均 untracked**（verify §5 全 `??`）：FREEZE 已记 sha，但正式跑前建议 git commit 固化，防脚本被改动后无从对账。
4. `fpf_ids`（filler 在 no_card 通过实例上翻 fail）已计算，但是否写入 analysis_s1.json/md 不在摘录内（spec §4.2 要求描述性报告）。
5. bundle "build_prompt (111-115)" 节摘录内容实为 load_pool；build_prompt 本体未直接摘录，等价性以 verify BUILD_EQ 为准。

## 只读声明

- 只读取 `/tmp/s1_review_bundle.md`（142 行）；只执行 `python3 /tmp/s1_verify.py`（36 行输出，总 exit 0）。
- 未读 run_s1.py / analyze_s1.py 源文件、未读 calls.jsonl、未读仓库内其他文件。
- 未修改任何既有文件；唯一写入为本报告 `docs/REVIEW-S1-CODE-20261019.md`（新增）。
- 未联网；未调用正式模型 API（verify 全程 dry-run/smoke 本地构造数据，无真实推理调用）。
- smoke 数值（G1=28/G2=3/F1=0）为构造数据的门槛逻辑验证，非真实实验结果。
