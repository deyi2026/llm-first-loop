# 从"改模型"到"改外壳"：RRSI 与 LFL 的自我进化对照

> **状态**：内部草稿（2026-10-25），尚未对外发表。
> **事实分层**（本文沿用 LFL 三层纪律）：
> - 🟩 **可核事实**：RRSI 论文摘要页与全文（arXiv:2609.24972 / v3 HTML）与 LFL 仓库文档，均给出来源；
> - 🟨 **二手解读**：头条解读文，仅用于论文未覆盖的四处——三类病症命名、skill 与 subagent 两项、30 轮结局分布图、收束引语；§4.1、§4.2 的数字已由论文表格独立佐证；
> - 🟦 **作者判断**：对比分析与建议，可被推翻。
> **发表约束**：按 RULE-AI-28，对外发表前须取得独立文稿审查子代理对**当前产物**的有效 PASS 回执；本稿尚未过闸。

---

## 0. 一句话导读

过去谈"AI 自我改进"，你想的多半是它改自己的权重。今天最现实的一条路是：它改自己身上那层"壳"——提示词怎么写、工具怎么调、记忆怎么管、上下文怎么裁。这层壳叫 **Harness**。

RRSI 论文（代码托管在 `google-research/rrsi`；提交人/第一作者 Peng Xia，🟩 arXiv 摘要页，完整作者名单未核验）的答案有点反直觉：**不是限制 AI 能改什么，而是限制它"怎么改"**。而论文里最值得看的也不是涨了几个点，而是一个反直觉结果——**进化分更高的那套，泛化反而更差**。

有意思的是：LFL 在自己的仓库里，已经独立走到了同一个问题的同一条路上，只是答案更保守、也更细。本文用 RRSI 当引子，把这条路线讲一遍，再逐条对照 LFL 现有的做法。

---

## 1. 名词速查：Harness、RSI、Evolve Set 与 OOD

**Harness（外壳）**：冻结的模型权重之外，围绕它的一整套东西——prompt、control flow、tooling、memory、context management。论文原话是：agent 的能力"largely magnified by its harness"。同一颗模型，装在不同的壳里，做出的事可以差很远。

**RSI（递归自我改进）**：让系统改自己的下一版，再让改完的版本继续改下一版。论文把"改 harness"这条路径称为 **agent-system level 的 RSI**——不动权重，只动壳。

**Evolve Set（进化集）**：反复用来产生反馈、驱动修改的那批任务。**OOD（out-of-distribution）**：进化过程中从未见过的任务。

一句话抓住全文的张力：

> **在 Evolve Set 上变强，和离开 Evolve Set 之后还变强，是两件事。**

RRSI 的整套设计，就是为了让这两件事尽量对齐。

---

## 2. 老毛病：越改越强，还是越刷越熟？

传统 Harness Evolution 的流程很直观：当前 Agent 在一批任务上跑 → 从成功/失败轨迹里产生反馈 → 让 LLM 改 Harness → 新 Harness 放回**同一批**任务上评测 → 分数更高的留下，进入下一轮。

问题在于，这批任务会被一遍又一遍地用。第 1 轮的修改来自它们，第 30 轮还是它们。整个过程逐渐变成**对有限数据的持续自适应搜索（adaptive search）**——这在机器学习里是个熟悉的名字：**过拟合**。

🟨 解读文把论文描述的现象归纳成三类具体病症（论文本身未用这套三分类）：

| 病症 | 白话解释 | 后果 |
|---|---|---|
| **benchmark-specific fitting** | 记住这一套题独有的套路 | 在见过的题上越来越强，换题就废 |
| **evaluation noise chasing** | 把随机涨分当成真进步 | 把噪声写进永久状态，越改越歪 |
| **complexity accumulation** | 不断加 prompt、加 context、加恢复逻辑 | 每轮推理越来越贵，收益却越来越小 |

于是出现那个反直觉现象：**Evolve Score 一路上涨，OOD 上的收益却迅速缩水甚至消失。**

> 📌 这里有个容易被跳过的细节：所谓"分数上涨"，在单次评测里可能根本就是噪声。所以论文专门画了一条 **noise-adjusted floor（噪声底）**——低于这条线的"提升"，不能算进步。这是后面所有选择门的地基。

---

## 3. 药方：把"提什么"和"留什么"分开治

RRSI 最关键的设计判断是：**不锁死自我修改空间**。

🟩 论文摘要点名的可改项是：prompts、control flow、tooling、memory、context management。换句话说，AI 仍然拥有一个开放的 self-modification space。

🟨 解读文另外提到 skill 与 subagent 也可增删——论文正文可见 "memory and skill files"，但"subagent 可增删"未在论文核到。

那 Regularize 的是什么？是**它在这个空间里"怎么搜索"**。论文把 Harness RSI 拆成两个子问题，分头治：

### 3.1 Proposal 端：管"下一轮该试什么"

- **时间退火的预算（temporally annealed budget）**：前期允许更广的探索，**随着进化推进，每轮允许同时捆绑的修改越来越少**。理由很实在——同时改的地方越多，越说不清是哪一处起了作用。后期每次只动一个，功劳才分得清。
- **保留完整进化史**：哪个假设成功过、哪个机制已经失败过、某次修改涨了多少分、花了多少成本，都留着，成为下一轮的证据。
- **停滞时换方向**：搜索长期停滞，就把一部分探索容量转向此前较少被碰过的 harness 组件。

### 3.2 Selection 端：管"谁有资格留下来"

一个候选（candidate）**不会因为"分数涨了"就自动成为下一代 harness**。

- **Critic（审查者）**：提前筛掉 benchmark-specific 的提案。
- **Pruner（修剪者）**：删掉三类东西——**太小**的改动（落在噪声里）、**太贵**的改动（加了 context/token 但收益不匹配）、**不再有用**的改动（长期没有贡献的机制直接被裁掉）。
- **额外 context 必须自证**：新加的上下文必须用足够的性能提升来证明自己的存在价值。

> 一句话记住：**RRSI 不是阻止 AI 变化，而是要求每一个想永久留下来的变化都必须"证明自己"。**

---

## 4. 三组关键数字（以及它们为什么会反直觉）

### 4.1 消融实验：进化分更高 = 进化更差

在 Agentic Workspace 上，去掉 Regularization 的"裸进化"与 RRSI 对比：

| 指标 | 裸进化（无正则） | RRSI | 谁更好 |
|---|---|---|---|
| Evolve Score（进化集上） | **92.8** | 90.5 | 裸进化高 |
| OOD Average（未见任务） | 40.3 | **43.6** | **RRSI 高** |
| Policy Tokens / Trial | 3.80M | **2.42M** | **RRSI 少** |

如果沿用"训练分数越高越好"的直觉，第一行会让人选裸进化。但后两行说明：裸进化**迁移更差、还更贵**。

> 这就是本文最想传达的一条认知：**对 RSI 来说，最大化"眼前的改进"，本身就是一种 overfitting。**
> 🟩 上表三行与论文 Table 2 逐项吻合（92.8 / 90.5、40.3 / 43.6、3.80M / 2.42M）；2026-10-25 独立审查实测。

### 4.2 迁移：8 个 Benchmark、3 个 Domain、只在一个上进化

实验设置很硬：**Harness 只在一个 Benchmark 上进化，然后冻结、不再做任何修改，直接放到整个过程中从未见过的 Benchmark 上测。**

🟩 8 个 benchmark 是：Terminal-Bench 2.1、SWE-bench Verified、Harvey LAB、JobBench、GDPval、APEX-Agents、EngDesign、Frontier-Eng；三个域各自的**进化基准**分别是 Terminal-Bench 2.1（coding）、Harvey LAB（agentic workspace）、EngDesign（engineering design）。

| Domain | 进化于 | 迁移到 | 前 → 后 | Δ |
|---|---|---|---|---|
| Coding | Terminal-Bench 2.1 | SWE-bench Verified（Claude run） | 82.0 → 83.8 | +1.8 |
| Coding | Terminal-Bench 2.1 | SWE-bench Verified（Gemini run） | 76.8 → 79.0 | +2.2 |
| Agentic Workspace | Harvey LAB | JobBench | 36.0 → 40.7 | +4.7 |
| Agentic Workspace | Harvey LAB | GDPval | 48.8 → 52.3 | +3.5 |
| Agentic Workspace | Harvey LAB | APEX-Agents | 34.2 → 37.9 | +3.7 |
| Engineering Design | EngDesign | Frontier-Eng | 17.7 → 22.0 | +4.3 |

"进化基准本身"的涨幅也在同一批表里：Claude run 在 Terminal-Bench 2.1 上 74.2 → 80.2（**+6.0**，即摘要所说的 evolve split 最高增益），Gemini run 64.6 → 78.7（**+14.1**）；Harvey LAB 作为进化基准 89.4 → 90.5；EngDesign 50.0 → 54.9。另有同域的 Harvey LAB held-out ID 切分 86.9 → 89.2（+2.3）——论文正文明写 "The in-distribution held-out split of Harvey LAB gains 2.3"，Table 1 的行标签即 "Harvey LAB (ID Held-out)"。论文 Table 7 还给出两次独立运行的 OOD 均值 43.6 与 43.7。

🟩 **论文摘要页可核**：RRSI 在 8 个 benchmark、跨 coding / agentic workspace / engineering design 三域，"gains up to 6.0 points on the split it evolves against and up to **4.3** points on the five out-of-distribution benchmarks"，且 harness "runs on **30% fewer policy tokens** than the unregularized evolution"。

🟨 **两处口径差异（如实并列，不替论文裁定）**：
1. 论文**正文**写 "three out-of-distribution agentic benchmarks gain between 3.5 and 4.7 points"（JobBench 36.0→40.7 即 +4.7），**摘要**却写 "up to 4.3"——这是论文正文与摘要自身的不一致，论文未解释原因。
2. 2.42M vs 3.80M 约合少 36%，摘要说少 30%——同样可能是聚合口径不同，论文未说明。

引用这两组数字时请同时标明"正文口径"或"摘要口径"。

### 4.3 成本：更好的泛化，不需要更重的壳

论文把"每个 Trial 的 Policy Tokens"画成横轴、"OOD Average"画成纵轴，发现 RRSI 处在**"更少 Token、更高 OOD"**的右上角。

机制上也说得通：Regularization 阻止没有收益支撑的复杂度增长，还会**删除已经不再贡献的机制**。所以 RRSI 的泛化不是靠"往壳里塞更多东西"换来的。

> 🟦 判断：这条和 LFL 的成本纪律方向一致（见 §6.4），但两边的成本口径不同——RRSI 数的是 policy token，LFL 数的是"每个被接受改进的总成本"。

---

## 5. 活下来的改动，是极少数

论文自己的记录已经够说明问题：**20 轮评估了 32 个候选，最终只接受 4 个改动**（🟩 附录 F，agentic 一侧；附录 E.1 记三个域的进化轮数为 coding 20 / agentic 20 / engineering 40）。

解读文另转述了一张 30 轮的结局分布图（🟨，其图 6）：

| 结局 | 次数 |
|---|---|
| ✅ 被接受，成为新一代 Incumbent | **10** |
| ↔️ 有产出但 measured gain 不足 | 9 |
| ⛔ Screening 阶段就被拒 | 6 |
| 💥 没通过 Smoke Test | 2 |
| ∅ 那一轮没产生 Proposal | 3 |
| **合计** | **30** |

🟨 **这条 30 轮口径未在论文中找到**：论文附录记的是 20 / 20 / 40 轮，没有这条分布图。模型名不是问题——论文 Table 3 的行标签与正文用的就是 **Gemini 3.5 Flash** 🟩；**没有的是轮数**：论文未标注该 run 的轮数。图中的 64.6 → **78.7（+14.1）** 出自论文 Table 3 的 Gemini 3.5 Flash coding run 🟩。**引用这组 10/9/6/2/3 计数时请注明"解读文口径，论文未复核"。**

候选分数的一点点变化，说明不了 AI 真的进步——论文在曲线上画出的 noise-adjusted floor（噪声底带）就是这个意思：**一个修改只有提供了足够可信的证据，才有资格进入下一代 harness。**

> 🟨 解读文自己的收束句（逐字引用，也是这篇科普最想留给你的一句）：
> **"Recursive Self-Improvement 的重点，不是让更多修改存活，而是让真正有用的修改存活。"**
>
> 🟩 论文 §6 结论里的对应原句：
> **"requires controlling not only what can change, but also how repeated feedback is converted into persistent changes"**
> （不只要控制"什么能变"，还要控制"反复反馈如何被转成持久改动"。）

---

## 6. 对照：LFL 在同一道题上的答案

LFL 不是"看了这篇论文之后才开始想 RSI"——仓库里 `docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md`（v1.1，2026-10-19）已经独立把同一个问题拆成了 R1–R16 与 S0–S3。下面按 RRSI 的六个部件逐条对。

### 6.1 变异空间：RRSI 放开，LFL 上锁

- **RRSI**：🟩 论文摘要列出的可改项是 prompts、control flow、tooling、memory、context management；🟨 解读文另称 skill、subagent 也可增删（未在论文核到）。共同点是不锁死自我修改空间。
- **LFL**：R1 变异空间白名单（方法卡 / 提示词模板 / 工具选择策略 / 检索参数 / 流程脚本的**非安全段**）；R7 权限不变量（工具白名单、网络开关、写盘范围、外发通道、授权额度不得被改动）；v1.1 又把 R7 扩成"**信息流不变量**"（数据可去域、证据必须在 prompt 内、写盘前缀白名单、网络出口白名单），并要求卡正文改**结构化槽位渲染**（trigger/action/stop/verify），禁止自由指令段——因为在 LFL 里"**卡即注入面**"。

🟦 判断：这不是"谁更保守"的问题，而是**场景不同**。RRSI 的自由度建立在研究 harness 上；LFL 是带真实权限、外发通道和上线数据的系统，把 shell 全开放等于把事故开关交给自动搜索。

**但有一处更根本的差距要说清楚**：LFL 当前真正在"进化"的是**知识层（Method 卡）**，不是 harness 层。

- Method 生命周期：`candidate → qualified/active → hold/retire/invalidated`，`method_manage` 负责状态流转；`save_candidate` **永不覆盖**已有 candidate；Teacher 资产不可变。
- Method **不自动注入**：程序不替模型判断适用性，是否检索/水合由模型决定；读到卡不等于用上卡（usage 回执 `application_proven=false`）。
- `record_use` 只是"我用了/我改了/不适用/我否了"的声明，**不改状态、不构成资格证据**；资格要靠独立的 qualification 回执（verdict / mechanism / task benefit / promotion 分开记）。

也就是说：RRSI 进化的是"这层壳怎么长"，LFL 进化的是"我知道哪些坑"。LFL 想要 RRSI 那种 harness 级进化，第一步不是抄 critic，而是先把"哪些东西允许被自动改"的白名单切出来。

### 6.2 裁判与噪声：同一道题，LFL 更细，但闸门还没过

| | RRSI | LFL |
|---|---|---|
| 终极裁判 | 冻结后放到**从未见过的 OOD benchmark** | **卡依赖实例集 D**（held-out 语义） |
| 噪声处理 | noise-adjusted floor；落在 floor 内的涨分不算数 | 噪声底标定（同卡同条件重跑 ≥3 次，记录翻转 check 数与**翻转源**）；正式比较 ≥5 次配对报 95% CI |
| 对照组 | critic 筛掉 benchmark-specific 提案 | 阳性对照 gold 卡 + 阴性对照 filler 卡；filler 翻 ≥1 个实例即停 |
| 接受判据 | 增益超过噪声底且收益覆盖成本 | McNemar 精确检验单侧 p<0.05 且 \|D\|≥30；回归哨兵上无关家族翻转 ≤1 题；**只有 patch 相对 filler 的 Δ 才算效应** |

LFL 这边已经被自己的坑教育过一轮，这些坑就是 RRSI 说的"evaluation noise chasing"的具体形态：

- 同一张卡跑 5 次，分数是 9、7、7、9、7——极差 2 个 check ≈ 20 个百分点；翻转源是一处**自报计数**字段；去掉该字段后 5 次全是 7/8。
- 33 题 / 129 check 的池里，1 题 = 3.03pp、1 check = 0.78pp；配对 n=33、discordance≈0.5 时 **95% CI ≈ ±17pp**。在这个方差下，"涨了 2 分"基本等于没测出。
- P28 试点里，4 条 check 修过 3 版，而且**三次修订都让 orig_card 更容易过**（方向性风险）。到 104/240 次成功调用（51 对配对）时，v1.3 下 D=10，线性外推 120 对约 D≈23（95% CI 12–34，下沿低于 30）。于是提前写死了两条纪律：**v1.0 与 v1.2 必须同时满足 |D|≥30 才算过线**；过不了就写"该决策点在本仪器下不可测"，**不回头微调正则去凑**。

🟦 判断：**RRSI 用"一个从未参与进化的 benchmark"当终极裁判，LFL 用"卡依赖实例集 D"当终极裁判——这是同一个思想的两种实现。** LFL 这条线目前还没走完（P28 尚在 S0-2，|D| 贴着 30 的闸门），但"过不了就写不可测"和 RRSI 的 noise-adjusted floor 是同一种诚实。

### 6.3 复杂度积累：LFL 的对应物是"退役"，但更依赖自觉

- **RRSI**：pruner 自动删掉太小、太贵、不再有用的机制。
- **LFL**：`method_manage(transition=retire/invalidate)`、`refine_experience(archive/invalidate/restore)`；RULE-AI-29 要求用后负反馈在收口前闭环（2026-10-18 起不再强制 `record_use`，但"卡本身错了要当场处置"仍然生效）。

🟦 判断：**RRSI 的 prune 是流水线的一部分，LFL 的 prune 依赖模型记得去做。** LFL 有 `settlement_submit` 记账（工作单元 × 对象 × 版本抵扣），能暴露"读了很多但没用上"的卡片，但目前**没有"贡献度低 → 自动退役"的阈值机制**。

### 6.4 成本：口径更全，但缺了"泛化"那一维

- **RRSI**：policy tokens 直接进图，少 30%，并与 OOD 构成二维权衡。
- **LFL**：R5 规定成本要含**失败重试、超时、评审工时、一次性仪器成本**，报的是"**每个被接受改进的总成本**"——口径比 RRSI 更全。
- 现状数字（🟩 `docs/EVAL-REPORT-LFL-v1.md`，2026-10-23 草稿）：域内 v2 能力探针集 84 样本，tokens_in 7,363,157 / tokens_out 251,717；单样本 tokens_in 中位 24,855、均值 87,656（长尾来自多轮链式场景）；当日缓存命中率 0.936。主口径通过率 70.2%（59/84，Wilson 95% CI [0.598, 0.790]），排除轮数耗尽样本后 81.2%（52/64），截断率 23.8%。

🟦 判断：**没有 OOD 维度，成本优化很容易退化成单纯省钱。** LFL 现在的成本纪律是"别乱花"，RRSI 的成本纪律是"每多花 1 份 token，必须换来至少 1 份迁移收益"——后者更硬，也更难作弊。

### 6.5 停滞与探索：LFL 缺了"欠探索调度"这一格

- **RRSI**：停滞时把一部分 capacity 转向此前较少被探索的 harness 组件；保留完整进化史供下一步取用。
- **LFL**：`self_evaluate` 记成功率/停滞/异常；ReflectionRun 有机械摩擦触发（轮数、工具调用数、工具失败数、重复调用、停滞终止原因），产出 candidate；方法检索是模型自主选择，不是自动调度。

🟦 判断：LFL 有"停滞检测"和"经验产出"，但**没有"这个机制很少被碰过"的显式记账与调度**。系统不会因为"这块几乎没人踩过坑"而自动把探索预算推过去。这是 RRSI 里最容易抄、也最便宜的一处。

### 6.6 人类门：这一轴 LFL 更强

- **RRSI**：🟩 独立审查通读论文摘要/§1–§6/结论/附录 A,C,D,E,F（约 68k 字符），**未发现人工审核、人类门或对进化过程的监督环节**；附录 B.5 的 "human expert deliverable" 是 GDPval 的评分基线，不是监督。
- **LFL**：RULE-AI-28 三道审查闸（代码全量测试前 / 文稿发表前 / push 前），审查者与执行者分离、回执落盘、产物 SHA 绑定；`review_admission` 已实现真实准入（HostReviewAdmission）；`docs/STACK.md` 把 L3 用户层定为授权真值，L2 越权只能 `submit_evolution` 提建议。局限也要说清：目前 `review_admission` **不覆盖任意 shell、未知脚本、名称含糊的网页按钮**，也不等于 OS 级原子防旁路。

---

## 7. 一张总表

| 维度 | RRSI（论文，🟩摘要/🟨解读） | LFL（🟩仓库事实） | 判断 |
|---|---|---|---|
| 进化对象 | Harness 全壳：prompt / control flow / tool / memory / skill / context / subagent | 知识层 Method 卡；harness 层仅在 R1 白名单内、尚无自动通道 | LFL 层次更窄，安全但功能落后 |
| 变异空间 | 开放 | R1 白名单 + R7 权限不变量 + 信息流不变量 | 生产系统应如此 |
| 终极裁判 | 从未见过的 OOD benchmark | 卡依赖实例集 D | 同一思想的两种实现 |
| 噪声处理 | noise-adjusted floor + critic 筛掉 | 噪声底标定 + gold/filler 对照 + McNemar + \|D\| 门槛 | LFL 更细，但闸门未过 |
| 复杂度治理 | pruner 自动删除 | 退役/失效，靠模型主动 + 结算记账暴露 | LFL 更弱 |
| 探索调度 | 欠探索组件优先 + 退火预算 | 停滞检测 + 反思产出候选，无组件级调度 | LFL 明确缺口 |
| 成本口径 | policy tokens（少 30%），与 OOD 构成二维图 | 每个被接受改进的总成本（含失败/超时/评审/仪器） | 口径 LFL 更全，缺 OOD 那一维 |
| 人类门 | 🟩 论文通读范围内未见人工审核门 | RULE-AI-28 三闸 + L3 授权真值 | LFL 更强 |
| 验证规模 | 8 benchmark / 3 domain / 每域 20–40 轮（🟩 附录 E.1；🟨 另有解读文的 30 轮曲线） | 单决策点试点（P28），S0-2 进行中 | 差着数量级 |

---

## 8. 可以抄的三件事，不该抄的两件事

### 值得直接抄

1. **把 OOD 立为一等公民**：每次接受一个改动，都要在"从未参与修改的题"上再测一次。LFL 已有 D 的设计，缺的是把第二把尺变成常规动作，而不是只在验收时才想起来。
2. **成本—泛化二维权衡**：不只看"涨了几分"，同时看"多花了多少 token"。只接受落在"更省且更泛化"区域的改动；反过来，**只涨分不涨泛化的一律不算改进**。
3. **退火预算 + 欠探索调度**：早期允许捆绑改动，后期一次只动一个，好归因；停滞时把探索容量推向少被碰过的机制。附带一条零成本的：把 noise-adjusted floor 画进每一张进化曲线。
4. **一句话纪律**（可以直接抄进 LFL 的验收口径；🟨 来自解读文收束句）：*Recursive Self-Improvement 的重点，不是让更多修改存活，而是让真正有用的修改存活。*

### 不该抄

1. **别照搬"开放整个 harness 空间"**：LFL 带真实权限与外发通道。RRSI 的自由度是研究 harness 的自由度，不是生产系统的。
2. **别在没有兜底尺的情况下把接受动作自动化**：RRSI 的 critic/pruner 敢自动跑，是因为背后有冻结的 OOD benchmark 兜底；LFL 目前连 P28 的 \|D\|≥30 都还没过线。此时自动接受 = 自动过拟合。
3. **抄机制，别抄规模**：RRSI 的结论建立在 8 个 benchmark × 3 个域 × 每域 20–40 轮进化（🟩 论文附录 E.1）的搜索量上。LFL 的算力预算支撑不了同规模实验；把它缩成"一个决策点 + 一把兜底尺 + 一张二维图"，才是能落地的版本。

---

## 9. 核对与未核验清单

### 本次实际取证（可复核）

| 来源 | 取到了什么 |
|---|---|
| 🟩 arXiv:2609.24972 摘要页 | 标题《RRSI: Regularized Recursive Self-Improvement of Agent Harnesses》；提交人 Peng Xia；v1 2026-09-21、v3 2026-10-04；方法描述（annealed budget、critic、pruner、history-guided exploration）；evolve split 最高 +6.0、5 个 OOD benchmark 最高 +4.3；policy tokens 少 30%；代码 `github.com/google-research/rrsi`、项目主页 `regularized-rsi.com` |
| 🟩 arXiv:2609.24972v3 全文 HTML（独立审查分页抓取，约 68k 字符，覆盖摘要/§1–§6/结论/附录 A,C,D,E,F） | Table 1/2/3/4/7 逐项数字（本文 §4.1、§4.2 全部命中）；8 个 benchmark 与 3 个进化基准；轮数 20/20/40；附录 F "Four edits accepted out of 32 evaluated candidates over 20 rounds"；§6 结论原句；通读范围内未见人工审核 / 人类门 |
| 🟩 `docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md` | R1–R16、S0–S3 执行顺序、F1–F6 实测事实、P28 试点池与 check 版本演进、噪声底与 MDE 数字 |
| 🟩 `docs/METHOD_LEARNING_V1.md` | Method 状态机与"永不覆盖/不自动注入/teacher 不可变"、usage 回执语义、reflection 摩擦触发条件 |
| 🟩 `docs/STACK.md` | L1 程序 / L2 模型 / L3 用户三层权威边界与"下层不得扩大上层授权" |
| 🟩 `docs/EVAL-REPORT-LFL-v1.md` | 域内 v2 探针集 84 样本的三口径结果、成本与缓存命中、场景级通过率、"护栏生效"场景本次不作结论 |
| 🟩 `docs/ai_rules.md` | RULE-AI-28 三闸与回执要求、RULE-AI-29 用后负反馈闭环 |
| 🟨 头条解读文（本次输入链接） | §2 的三类病症命名、§3/§6.1 的 skill 与 subagent 两项、§5 的 30 轮结局分布计数（10/9/6/2/3）、§5 的收束引语——**这四处未在论文中核到**；§4.1、§4.2 的数字与 "Gemini 3.5 Flash" 模型名已由论文表格与正文独立佐证 |

### 未核验 / 存疑（引用时必须标注）

1. **论文正文未逐字覆盖的部分**：独立审查通读了摘要/§1–§6/结论/附录 A,C,D,E,F，参考文献区有两小段未逐字读；不影响已下判定。
2. **完整作者名单未核**：arXiv 摘要页只显示提交人 "From: Peng Xia"，HTML 脚注称其时为 Google Cloud AI Research 学生研究员；若存在共同作者，本文只写"提交人/第一作者"是有意保守。
3. **"30 轮"这条进化曲线存疑**：论文附录记 20/20/40 轮，未给这条分布图；解读文的 10/9/6/2/3 计数属 🟨。项目网站 `regularized-rsi.com` 本次未访问，若其图 6 有对应原始数据，应据此复核。
4. **论文正文与摘要自身的口径差异（未裁定）**：正文 "between 3.5 and 4.7 points" vs 摘要 "up to 4.3"；2.42M vs 3.80M 约少 36% vs 摘要少 30%。论文未解释，本文并列保留。
5. **LFL 侧 P28 试点为进行中读数**：§6.2 引用的 D=10、外推 D≈23 属中途读数，非终值；结论须以 240 次调用跑完后的终值为准。

### 发布前必做

按 RULE-AI-28（文稿闸）：交独立审查子代理对本稿**当前产物**做事实可核性（数字/引文/归属逐条对证据）、合规（AI 声明、尾注自洽）、结构完整与平台残留扫描，取得落盘 PASS 回执后方可对外发表。

过程记录（2026-10-25）：

- **全量审查**：`docs/promotion/receipts/20261025-rrsi-lfl-review.json`，verdict=REVISE，P1×3、P2×3；已按其修订 P1-1 / P1-2 / P1-3 / P2-1 / P2-2，并采纳 P2-3 的升标（§4.1、§4.2 数字改标 🟩）。
- **窄复审第一轮**：6 条旧发现**全部 fixed**，另提 4 条新发现（NF-1、NF-2 为 P2；NF-3、NF-4 为 P3）；本稿已按其修订——改正两处与论文原文相悖的元断言（Harvey LAB 的 held-out ID 切分、Gemini 3.5 Flash 模型名），并同步总表与文首口径。
- **当前状态以回执文件为准**：对外发表前须确认该回执对**当前产物**给出 PASS；未取得前，本稿仍属内部草稿，不得对外发表。

---

## 10. 结尾：两种"不作弊"

RRSI 那篇论文最值得带走的，其实不是任何一项具体技术，而是两个可以互相印证的判断：

1. **对 RSI 来说，最大化"眼前的改进"，本身就是一种 overfitting。** 分涨得再好看，不迁移到没见过的任务上，就不算数。
2. **自我改进这件事本身，也需要被"正则化"。** 搜索方式要被约束、证据不足的改动要能被拒、没用的机制要能被剪掉。

LFL 在这上面走的是另一条风格的路：把"什么能被改""谁来判""怎么证明没作弊""谁来放行"逐条写死，写成 R1–R16，写成三道审查闸，写成"过不了就写不可测"。慢，但每一步都可复核。

两条路要回答的是同一道题：**你怎么知道自己真的变好了，而不是只是更会做自己见过的题？**

> 论文：RRSI: Regularized Recursive Self-Improvement of Agent Harnesses — arXiv:2609.24972 · `github.com/google-research/rrsi` · `regularized-rsi.com`
> 本文是解读与对照分析，不构成对任何权限、规则或评估口径的变更；文中 LFL 侧事实均可在本仓库文档中复核。
