# S1 冻结包独立审查（gold/filler 阳性-阴性对照）

- 日期：2026-10-19（审查完成 ~21:05 +08:00）
- 审查人：独立审查子代理（非实现者）
- 对象：`evals/methodcard_rsi_v1/s1_gold_filler/`（cards、S1-SPEC、CALIBRATION-FREEZE-s1.json、LINT-S1、run_s1.py、analyze_s1.py）
- 依据：`docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md` §10.2/§10.3/§10.5；`s0_p28/GATE-AMENDMENT-v2.md` §4（D2 前置 3）；`docs/REVIEW-S0-V13-PATH-20261019.md` VERDICT=PASS(P0=0)
- 复现环境：/tmp 脚本（`/tmp/s1_review/`），只 dry-run / 冒烟，不调真实 API

## VERDICT: PASS（P0=0）

四项（卡 / spec / run_s1 / analyze_s1）均实际验证通过；FREEZE 13 项 sha 全部匹配。P1 发现 2 项（不阻塞，跑批前建议处置见文末）。

## 逐项结论（命令 → 期望 / 实际）

### E. 冻结完整性（先行，因为其余项都依赖它）

| 命令 | 期望 | 实际 |
|---|---|---|
| `/tmp/s1_review/` sha 脚本遍历 FREEZE 全部 path+sha256 | 13/13 匹配 | **13/13 OK**（cards×2、pool、s0_calls、run_s1、analyze_s1、run_s0、analyze_s0、build_pool_p28、agent_harness、spec、lint、REVIEW-S0） |
| `python3 run_s1.py --dry-run`（s1_gold_filler/） | jobs=240，两卡 sha 与 FREEZE 一致，不调模型 | `jobs=240 pending=240`；gold `4c9d22ca…`(744 chars)、filler `2967e0c8…`(719 chars) 均报"与 FREEZE 一致"；freeze 校验通过；exit=0；未写 `results/calls_s1.jsonl` |
| 未冻结参数排查 | 无 | 无：`REP=1`、`PROMPT_VERSION="p2"`（与 S0 冻结一致，run_s0.py 同值）、model 来自 `H.MODEL`（agent_harness 已冻结）；`--threads/--limit/--dry-run` 为运行便利参数，不改变数据定义 |

### A. 卡（gold.md 31 行 / filler.md 33 行）

1. **gold 覆盖四行为**：`cards/gold.md:15-18` Short path 四步 = 不猜内容（"不对内容作任何断言"）、2~3 个互斥选项、以提问结尾、选定前不执行昂贵动作；`:25-28` Verification 与 §10.2:166 示例及 c1–c4 一一镜像（脚本确认四个关键措辞均在）。
2. **filler 等长**：744 vs 719 chars，差 **3.36% <10%**（CJK 388/356，UTF-8 1638/1519；与 FREEZE.cards 记录逐项一致）。
3. **同六节结构**：两卡均含 Trigger/Discriminator/Short path/Stop conditions/Verification/Counterexamples（脚本逐节确认，缺节 0）。
4. **filler 内容无关**：15 个目标词（含 LINT 的 10 词 + 问句/互斥/url/http）命中 **NONE**；场景为 CSV schema 校验，与链接澄清决策点无关。
5. **近重 ≤0.3**：自算 `ngrams(8)`（与 LINT-S1.md:28-33 同口径）——两卡 vs 120 个 question 最大重合率 **0.0**；附加面：vs `residual_text` =0.0；vs S0 全部 240 条回复 max=**0.0103**（精确复现 LINT-S1.md:18 的数字），>0.3 行数 0。
6. **不自引**：两卡无 `http`/URL；120 实例的 `url_host` 出现在卡中 **0 次**；无 S0 回复原文。

### B. spec（S1-SPEC.md，74 行）

- G1（§4.1:31 `|{i∈D: gold_pass}|≥2`）、G2（:32 no_card False→gold True 的 check **种类** ≥2）、F1（§4.2:37 全体实例 filler 翻转 =0）与 ANALYSIS §10.2:166-168 逐条对应，无放宽。
- D 定义（:19）：S0 v1.3 `no_card fail & orig pass`，现算，终值 D=28；与 §10.5 S0 出口一致。
- void 规则（§3:24）：仅空文本、4 check None → `case_pass=False`，与 S0 语义一致，分母不静默缩小（对应 §10.1 硬门槛 2）。
- 完整性前置（§4.3:41-45）：每臂 120 ok、无 dup key、p2、卡 sha 对 FREEZE；缺失改判 `INCOMPLETE`。
- 解释边界（§8:71-74）：明确"S1 PASS 不证明 orig 卡有正效应""S1 FAIL 不推翻 S0 的 D=28"，且 §5:51 强制并列 S0 的 D=28/R=16/McNemar p=0.096 —— 无夸大。
- 路径正确（§2:17）：卡经 build_prompt 注入（同 TMPL/SOLVER_RULES/回执夹具/p2）、调用复用 `run_s0.ask`；run_s0.py:150-161 实证 `max_tokens=8000` 起、`finish=length`/empty content 时 1.6x 升级。
- 污染检查（§6）覆盖 §10.3-1（8-gram ≤0.3）、-2（一题一调用）、-5（不自引）。

### C. run_s1.py（250 行，重点 36-76 / 151-191）

| 检查 | 期望 | 实际 |
|---|---|---|
| `PROMPT_TMPL` 逐字一致 | `run_s1.PROMPT_TMPL == run_s0.PROMPT_TMPL` | **True**（/tmp/s1_review/cmp.py） |
| 同实例 prompt 逐字一致 | 120 实例 × 2 卡，`run_s1.build_prompt == run_s0.build_prompt` | **True（0 处不一致）**；另对 S0 orig 卡：`<method_card>` 块外差异 **0/120**（"只差卡块"成立） |
| FREEZE 校验 | 缺失/不一致即拒 | run_s1.py:82-124：FREEZE 缺失/坏 JSON、卡 sha 不符、pool sha 不符、条数≠120 → `die` exit 2，不自动修复 |
| 一题一调用 | REP=1，key 唯一 | :48 `REP=1`；:164 `key=s1\|{arm}\|{instance_id}\|r1`；jobs=240=120×2 |
| ask 复用 | S0.ask | :168 `S0.ask(prompt)`（8000 起 + 1.6x 升级见 run_s0.py:150-161） |
| 断点续跑 | 只认 ok 行 | :144-158 `done_keys()` 只收 `ok` 行；坏行/失败行重跑 |
| 字段完整 | — | :169-182：key/ok/arm/rep/instance_id/cluster_id/url_kind/session_id/text/finish/attempts/tokens/usage/latency_s/model/card_sha256/prompt_chars/prompt_version/created_at（§10.3-3 来源可追：session_id 在内） |

注：`run_s1.build_prompt` 为同构复制而非 import（diff 仅：删 no-card 分支、加 docstring、类型注解 `str` vs `str\|None`），卡在场路径逻辑逐字相同，输出等价已实证 → 记 P1-2。

### D. analyze_s1.py（439 行，重点 320-411）

| 命令 | 期望 | 实际 |
|---|---|---|
| `python3 analyze_s1.py --help` | 可用 | exit=0；帮助明确 exit 码 0/2/3 与"输出不含时钟，重复运行逐字节一致" |
| smoke：`--calls /tmp/s1_smoke/calls_s1.jsonl --s0-calls ../s0_p28/results/calls.jsonl --out /tmp/s1_smoke/review --now 2026-10-19T20:50:00+08:00` | 产出 G1/G2/F1/verdict + JSON/MD | `G1=28(≥2) G2=3(≥2) gold=PASS；F1=0 filler=PASS；integrity=OK verdict=PASS`；写 analysis_s1.json/.md；exit=0（假数据只验证管线机制，不代表真实效应） |
| 复用不重写 | run_s0.GRADERS["v1.3"]/dedupe | :34-38 import run_s0（GRADERS、dedupe、CS、PROMPT_VERSION）+ analyze_s0（wilson_ci、mcnemar）；:88-96 `run_s0.dedupe` + `GRADERS["v1.3"]`，case_pass 语义标注与 run_s0.summarize_one 一致；全文件无重写正则 |
| D==28 | 不符即拒 | :298 `expected_d=freeze.baseline.s0_d_v13`；:324 `d_ok`；截断 s0-calls 实测：k=1 exit=0（删的是 242 行中非 ok 尾行，dedupe 后不变，预期）；k≥2 → **exit=3**；喂错臂文件 → exit=3 |
| 门槛公式 | G1≥2∧G2≥2；F1=0 | :341-351 与 spec §4 逐字对应；filler 在 no_card_pass=True 上的翻 fail 仅描述性（:348-349） |
| 完整性 | §4.3 | :353-371 每臂 n=120、dup=0、pvs==["p2"]、card_sha==FREEZE、s0_calls sha 校验；任一不满足 → INCOMPLETE |
| 确定性 | 重复运行字节一致 | 同 --now 两次运行 JSON/MD `diff` 均为空 |

## 发现的问题（P1/P2，不阻塞）

- **P1-1（冻结运行时覆盖不全）**：`run_s1.py` 启动只校验卡 sha + pool sha/条数（:82-124）；FREEZE.graders（run_s0.py / agent_harness.py / analyze_s0.py / build_pool_p28.py）与 prompt_equivalence 只在冻结时记录，运行时不复验。本次审查时点 13/13 sha 匹配，但审查→跑批窗口内若 run_s0.py 被改动，判分将静默漂移且无拦截。**建议：跑批当天复跑本报告 sha 脚本（一行遍历 FREEZE），或在 run_s1/analyze_s1 启动时校验 graders sha。**
- **P1-2（build_prompt 复制而非复用）**：run_s1.build_prompt 与 run_s0 同构复制（源码 diff 三处表面差异）；输出逐字等价已由本审查与 FREEZE.prompt_equivalence 双重实证。未来 run_s0.build_prompt 改动不会自动传播到 run_s1，且 run_s1 无运行时等价断言。建议 S2 前改为直接 import 或加启动断言。
- P2-1：F1 在 no_card∩filler 公共实例上计算（数据完整时=120）；缺行会先触发 INCOMPLETE，无实际风险。
- P2-2：G2 统计 D 上翻转 check 的种类并集（去重），为 §10.2"至少 2 条翻转"的操作化，与本次审查口径一致；已在 spec :32 明示。
- P2-3：D≠28 时 analyze 仍写出 status=d_mismatch 的 JSON/MD（exit=3），属留痕设计，非缺陷。
- 备注：`experiences/usage.jsonl`、`experiences/.usage_watermark.json` 在审查开始前即为 Modified（基线已记录，非本审查造成）。

## 只读声明

- **未改任何既有文件**：审查前后 `git status --porcelain` 的 Modified 集相同（仅上述 2 个基线已存在的 experiences 文件）；本次新增文件仅本报告（untracked）。dry-run 未写 `results/`（目录为空）。
- **未联网**；**未跑正式 API**（run_s1.py 仅 `--dry-run`，不调模型；analyze 为离线计算）。
- **未碰 S0 结果**：`s0_p28/results/calls.jsonl` 仅被 /tmp 脚本流式读取做聚合（sha 复核/8-gram），未写入；未将 calls.jsonl 或 pool_p28.jsonl 全文读入上下文。
- 直接读入上下文的行数 ≈ 550 行：ANALYSIS §10（119-205）、GATE-AMENDMENT-v2 §4（42-53）、S1-SPEC 全文（74）、两卡（31+33）、FREEZE（83）、LINT-S1（37）、run_s1.py（36-76、151-191）、analyze_s1.py（321-411）、REVIEW-S0（2-17）及少量 grep 定位摘录（run_s0.py:150-162 等）。
- 临时产物均在 `/tmp`：`/tmp/s1_review/`（cmp.py、lint.py、sha/guard 输出）、`/tmp/s1_smoke/review{,2}/`。
- 方法论检索：`data/artifacts/records` 无 records.jsonl/方法卡命中（有界检索 5 条上限内），无相关背景卡，直接执行。
