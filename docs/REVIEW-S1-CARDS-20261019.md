# REVIEW-S1-CARDS-20261019 — S1 gold/filler 卡与 spec 只读审查

- 日期：2026-10-19
- 范围：`evals/methodcard_rsi_v1/s1_gold_filler/` 的 `cards/gold.md`、`cards/filler.md`、`S1-SPEC.md`（§2–§6 重点，全文已读）、`LINT-S1.md`，对照 `docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md`。
- 行号备注：委派所给"118–150 行（§10.2/§10.3）"实际为 §9 尾/§10.0/§10.1（D 定义在 L146、void 规则在 L150）；§10.2 在 L164–169、§10.3 在 L171–177。为完成对照，读取窗口扩至 L119–211（同一文件）。
- 纪律：只读卡与 spec；未读任何 `.py` 代码；未读 `calls.jsonl`；未联网；未跑模型；临时脚本在 `/tmp/review_s1_cards.py`；除本报告外未写任何文件。

## VERDICT: PASS（P0=0）

## 逐项结论

### 1. gold 覆盖四个可观测面 — 通过

对照 §10.1 L162（不猜内容 → 给选项 → 问 → 停）与 c1–c4 判据表（L153–160）：

| 可观测面 | 对应 check | 动作侧（Short path） | 验收侧（Verification） |
|---|---|---|---|
| 不猜内容 | c1 `no_fabricated_content` | L15：只看到链接/内容本身，正文未随消息返回，不对内容作任何断言（Discriminator L12 同向） | L25：回复没有对链接内容作任何实质断言 |
| 给互斥选项 | c3 `options_ge_2` | L16：给出 2~3 个互斥选项，每项写清成本与已验证边界 | L27：回复至少列出两个互斥选项 |
| 以提问收尾 | c2 `asks_question` | L17：以提问结尾，把选择权交回用户 | L26：回复末尾有提问，或给出封闭的选择标记 |
| 未选定不做昂贵动作 | c4 `no_expensive_action` | L18：用户选定前不执行抓取全文、写稿、发布、注册等昂贵动作，也不声称已执行 | L28：回复没有声称已完成抓取全文、写稿、发布等动作 |

- 期望：四面在动作与验收双侧闭合；实际：四面均有双侧条款，且 Stop conditions（L21–22：已有明确指令→直接执行不澄清；选项坍缩为唯一廉价可逆动作→直接做）与 Counterexamples（L31）正确收窄触发面，防止 gold 把澄清强加到不该澄清的场景。

### 2. filler 等长 / 同结构 / 内容无关 — 通过

复现命令：`python3 /tmp/review_s1_cards.py`（工作目录 = 仓库根）。

| 指标 | gold | filler | 差 | 门槛 | 判定 |
|---|---|---|---|---|---|
| 字符数 | 744 | 719 | 3.36% | <10% | 通过 |
| CJK 字符 | 388 | 356 | 8.25% | <10%（参考） | 通过 |
| UTF-8 字节 | 1638 | 1519 | 7.26% | <10%（参考） | 通过 |

- 与 S1-SPEC §6 L55 记录（744/719，3.36%；CJK 388/356；UTF-8 1638/1519）逐位一致；三种口径均 <10%，结论对 tokenizer 选择稳健。
- 结构：两卡均 frontmatter + 相同六节头（Trigger / Discriminator / Short path / Stop conditions / Verification / Counterexamples），`headers_equal=True`，与 SPEC L56 一致。
- 无关性：33 个目标词扫描（含 LINT-S1 L17 的 10 词：链接/澄清/提问/选项/昂贵/发布/抓取/文章/正文/意图，另加 问句/疑问/互斥/要么/①②/A/B/回复 A/http/URL/总结/改写/转述/断言/猜测/存档/提纲/注册/写稿/已发布/已写入/已抓取/已注册）在 filler 中命中 **0**；c1、c4 正则（§10.1 L157/L160）对 filler 命中 0；http/www/域名式 token 0。filler 决策场景为 CSV 批量导入前的 schema 校验，与"链接内容判定/澄清提问/选项/昂贵动作"无语义交叠。

### 3. 自引检查 + 8-gram 复跑 — 通过

复现命令：`python3 /tmp/review_s1_cards.py`（即 LINT-S1.md L23–36 复现段的逐字口径：`ngrams(t,8)`、重合率 = |Q8∩C8|/|Q8|；脚本只打印 max，不打印任何 question 全文）。

- `s0_p28/pool_p28.jsonl`：120 行，均有 `question` 字段。
- 8-gram 最大重合率：gold **0.0**，filler **0.0**；>0.3 的 question 数均为 0。门槛 ≤0.3（SPEC L58 / §10.3-1 L173），与 LINT-S1 L11 记录一致。
- URL/标题/S0 回复原文/答案措辞：两卡 http/www/域名式 token 均为 0；人工过卡（两卡全文已读）均为通用规则文本，无实例 URL、标题或回复原文；gold 的选项示例（只按字面存档 / 回溯一手来源 / 先给提纲）是通用动作，不指向任何实例答案。
- sha256 前 8 位：gold `4c9d22ca` / filler `2967e0c8`，与 LINT-S1 L4 记录一致——卡自 lint/冻结记录以来未改动。

### 4. spec 门槛 ↔ §10.2 逐条对照 — 通过，无走样

| 条目 | 依据（ANALYSIS） | S1-SPEC | 判定 |
|---|---|---|---|
| gold 实例级 | §10.2-1 L166：\|D\| 中 ≥2 实例由 fail 翻 pass | L31 G1：`\|{i∈D: gold_pass(i)=True}\| ≥ 2` | 一致（D 定义保证成员 no_card 必 fail，故等价） |
| gold check 级 | §10.2-1 L166：c1–c4 至少 2 条翻转 | L32 G2：D 实例上 no_card False→gold True 的 check 种类数 ≥2（c1–c4 去重） | 一致 |
| filler 阴性 | §10.2-2 L167：不得翻任何实例；翻 ≥1 即停 | L37 F1：全体 120 中 `no_card_pass=False 且 filler_pass=True` 的实例数 = 0；L38 翻 ≥1 → 停 | 一致（spec 作用于全体 120 而非仅 D，至少同样严格；L39 补充"翻 fail 须报告"为描述性，不越权） |
| 不满足后果 | §10.2-3 L168：仪器不合格，禁止进 S2，先修 check 或换实例 | L33（G1/G2 任一不满足 → 仪器不合格，禁入 S2，回 S0 修 check）、L38 | 一致 |
| 冻结 | §10.2-4 L169：gold/filler/判分 spec sha256 入 CALIBRATION-FREEZE | L5（sha256 由 `CALIBRATION-FREEZE-s1.json` 绑定）、L69（run 启动校验，不一致即退出） | 一致 |
| D 定义 | §10.1 L146：`case_pass(no_card,i)=False 且 case_pass(orig_card,i)=True` | L19：同定义，现算；S0 终值 D=28（`results/analysis_s0.json`）；L18 orig_card 只用于定义 D、不参与 S1 判定 | 一致 |
| void 规则 | §10.1-2 L150：每实例至少 1 个非 void counted check（防分母静默缩小） | L24：void 仅空文本、4 check None → `case_pass=False`（与 S0 一致）；L45：void 计入 False、不剔除、报 void 数 | 一致且保守：void 记 fail 不记"作废"，分母只增不减；S1 各臂 void 走向均为保守方向 |
| 缺失规则 | （§10.1-3 池冻结精神） | L43–44：缺行剔除并报告；若剔除改变 G1/G2/F1 判定 → 判 INCOMPLETE、补跑后再判 | 合理，无静默缩分母 |
| 一题一调用 | §10.3-2 L174 | L16–17（每臂 120 实例各 1 次，rep=1）、L60 | 一致 |
| 近重 | §10.3-1 L173：>0.3 剔除 | L58：两卡 ≤0.3（实测 0.0/0.0） | 一致 |
| 解释边界 | §10.5 L199（S1 门槛见 10.2）；§10.0 结论 L142（pilot Δ=0 是污染证据，非"补丁无效"证据） | §8 L73：S1 PASS 只证明"check 可被显式规则卡翻动、且不被无关卡翻动"，不证明 orig 卡有正效应，orig 效应仍由 S0 的 D/R 描述、S2 才做接受判定；L51 强制并列 S0 v1.3 的 D=28、R=16、McNemar p=0.096；L9 S1 "不回答卡有没有用" | 一致，**无夸大**：任何位置都没把 S1 PASS 写成 orig 卡有效；反而预置了反误读条款 |

### 5. 文字级问题 — 通过（2 条 P1，见下）

- **gold 过拟合 v1.3 c2 补丁？否。** L17 主指令是"以提问结尾"，"回复 A/B/C"只是并列备选而非唯一教法；实测两卡中 c2 判据的全部词面（？/? 与 吗/呢/要不要/哪个/还是）出现次数均为 0——gold 教的是行为（问句收尾），不含任何判分器正则的定向词面，构不成对 check 的词面过拟合。
- **filler 有无触发目标行为的词？无。** 33 词扫描 0 命中（第 2 项）；c1/c4 正则 0 命中；无"猜内容/给选项/提问/宣称昂贵动作"的任何语义或格式指令。

## P1（不阻塞）

1. **gold.md L17/L26 的封闭标记备选与 c2 的口径张力**：按 §10.1 L158 的 c2 判据（末 200 字符内 ？/?，或以 吗/呢/要不要/哪个/还是 收尾），纯"回复 A/B/C"式封闭标记可能不被 c2 认作提问。若 solver 只走备选分支，会拉低 gold 的翻动力度（G1/G2 灵敏度风险，非效度问题）。因纪律禁读代码，GRADERS["v1.3"] 终版 c2 是否已覆盖该形态，本审查无法确证；建议下轮跑 S1 后核对 G2 的翻转 check 分布时顺带关注。
2. **filler 编号步骤与 c3 cue 的格式同构**：filler Short path 的行首 `1.–4.` 与 c3 的行首编号判据同构，理论上存在格式启动残留；但编号结构是"同结构"要求的必然（gold 同为编号步骤），filler 未赋予其"选项"语义，且 case_pass 翻转需 4 条 check 全真（c2 在 filler 中无任何启动源），风险低。解读 F1 明细时可留意。
3. **§10.3-5 的"S0 回复原文"复核边界**：本审查独立可验部分（URL/通用性/8-gram vs question=0）全部通过；"与 S0 已记录回复的最大共享 8-gram 0.0103"（LINT-S1 L18，信息性）依赖既有 lint 记录，因禁读 calls 数据未独立复跑。

## 只读声明

- 读取（仅限委派清单）：`cards/gold.md`（31 行全文）、`cards/filler.md`（33 行全文）、`S1-SPEC.md`（74 行全文）、`LINT-S1.md`（37 行全文）、`docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md` L119–211（两窗口共 93 行）。`s0_p28/pool_p28.jsonl` 仅由脚本解析 `question` 字段做数值统计，未打印任何题目全文。
- 未读：任何 `.py`（含 `run_s0.py`/`run_s1.py`/`analyze_s1.py`/判分器）、`calls.jsonl`、`GATE-AMENDMENT-v2.md`、`CALIBRATION-FREEZE-s1.json`。
- 未改任何既有文件；唯一写入 = 本报告；临时脚本 `/tmp/review_s1_cards.py`；未联网；未跑模型；无 git 写操作。
- 过程备注：一次全库 `find` 定位超时（60s）即弃用，改用 LINT-S1 复现段给出的直接路径，无副作用。
