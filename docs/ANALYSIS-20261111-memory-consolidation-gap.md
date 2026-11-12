# Agent 记忆的「离线整理 + 纠错」层：本地实现现状核对与差距清单

**—— 只读核查报告，不含任何写入动作**

| 项 | 值 |
| --- | --- |
| 报告类型 | 现状核对 + 差距分析（对照 Anthropic《The components of agent memory》） |
| 观测时点 | 2026-11-11 21:43–22:00 CST，所有数字取自该窗口内的工具回执 |
| 分析主体 | LFL 主代理，对本仓库 `data/methods`、`experiences`、`src/llm_loop` 的只读取证 |
| 对照基准 | `https://www.anthropic.com/research/components-of-agent-memory`（第一手，全文 21,522 字符已读完） |
| 本轮写入 | **零**。本报告不修改任何卡片、账本或代码 |
| 证据分级 | E1 = 本仓库工具回执 / 原文全文；E2 = 二手转述；U = 未核实 |

---

## 0. 摘要：三句话

**第一句：我缺的不是整理能力，是整理的触发者。** 整理所需的零件大多已经存在（候选生成器、判据守卫、使用账本、结算通道），但没有任何周期或事件把它们串起来跑。`grep` 全仓 `consolidat|dream|nightly|compact_mem|memory_maintenance`，**零命中** [E1]。

**第二句：我的纠错是「命中驱动」而非「巡检驱动」，因此在结构上必然留下永久盲区。** 纠错只在某张卡被检索到、被使用、且产生负反馈时才被触发。一张从未被检索的错卡，永远等不到它的纠错事件。当前账本上 `invalid 7 + superseded 2` 对 946 张经验卡（0.95%），是这条机制的实测结果 [E1]。

**第三句：更麻烦的是，我的架构把「修正」的价格定得比「不修」高。** 卡片版本号 = 整文件内容哈希，改正文即作废该卡全部历史使用回执。所以理性选择是留着错的、别动它。这是制度性的反向激励，不是疏忽 [E1]。

---

## 1. 核对方法与边界

本轮只做四类取证，全部只读：

1. **池子规模与状态分布**：按**文件级**取每个 `METHOD.md` / 经验卡的首个 `status` 行统计（非 `grep -h` 行数——见 §3 G3.5，行数会因脏 front matter 多计 11 条）。
2. **整理/纠错代码路径**：全仓关键词检索 + 关键模块头部与类方法签名（`experiences/store.py`、`knowledge_score/card_writeback.py`、`scripts/method_mutator*.py`）。
3. **运行痕迹**：候选目录、评分 sidecar 实际文件数、同主题卡片的并存情况。
4. **规则承诺**：`docs/ai_rules.md` 中 RULE-AI-31 正文（检索→使用→留痕→处置）。

**明确未核**：注入层的实际条数与字节数。会话启动上下文声称加载「方法 13 条、经验 946 条」，与方法库实测 2,025 张之间存在落差，但**注入的真实装配逻辑与预算我这一轮没有核**，因此不写入结论，只列为待核项（§5 T1）。

---

## 2. 现状：四层结构逐层对照

按 Anthropic 原文的分层逐层落位：

| 层 | 原文定义 | 本地对应物 | 实测状态 |
| --- | --- | --- | --- |
| transcripts | 可搜索的事件流 | `data/archived_sessions`、事件存储、`session_digest` | 存在；`session_digest` 经 CLI **手动**生成，无自动调度 [E1] |
| notes | 执行中主动写的观察、规则、计划 | `experiences/*.md`（946 张）、`data/methods/*/METHOD.md`（2,025 张） | 规模已超原文任何单个 wiki 实验 [E1] |
| representations | Wiki 式交叉链接主题页 | 方法索引 + stable ref 精确水合；**无跨卡合并页** | 有索引，无整合层 [E1] |
| injected | 每会话预加载的少量信息/索引 | 启动上下文（规则索引 + 经验索引） | **规模未核**（§5 T1） |

**关键观察：我的强项和原文的强项不重合。**
原文花最大篇幅证明的是 `representation`（wiki）与 `dreaming`（离线整理）的价值；我恰恰在这两层最薄——有索引、无整合；有整理零件、无调度。而我的 notes 层（写入侧）是四层中最厚重的。

---

## 3. 差距清单

每条给：**证据 → 机制含义 → 与原文的对照 → 方向**。方向只写"该往哪边动"，不写实施方案——方案等 §5 的 T1/T2 有结果再定。

### G1 · 整理无调度：有零件，无触发者

**证据 [E1]**
- `grep -rniE "consolidat|dream|nightly|compact_mem|memory_maintenance" --include=*.py src/ scripts/` → **零命中**。
- `scripts/method_mutator.py`：确定性结构修复算子，产出 `review_required` 候选，注释自述"不接受自动上线"。
- `scripts/method_mutator_llm.py`：LLM 定向改写，产出候选。
- `scripts/method_gate_v2.py`：判据守卫，带哈希检查（卡被编辑即判 stale 拒绝出结果）。
- `data/methods/_candidates/` → **0 个文件**。

**机制含义**：整理的三个环节（生成候选 / 判据校验 / 人工裁决）都已建好，但**没有任何东西负责"到点就跑一次"**。这三个脚本当前的调用者是人（或代理临时想起来）。没有调度，整理频率就等于"被记起的频率"。

**与原文的对照**：原文明确说 dreaming"requires compute"，且 `Directing Claude to continuously check all its memories might not be practical`，建议聚焦在"likely to change"的信息上、或按访问频率调 cadence。**原文的结论不是"要有全自动整理"，而是"要有被调过节奏的整理"。** 我现在的状态是全有或全无里的"无"。

**方向**：先建一次性的、可手动触发的巡检，跑通一遍看产出质量，再谈 cadence。跳过"跑通"直接上调度，只会把一个没验证过的流程固定成周期税。

---

### G2 · 纠错是命中驱动，未命中即永久盲区

**证据 [E1]**
- RULE-AI-31 第 3 条：处置评估"仅针对已留痕的负反馈"；只有 `record_use(rejected)` 才当场评估 `refine`/`hold`/`invalidate`。
- `usage_net` 在工具回执中明确标注为「只读派生视图（只读汇总，不改账本、不裁决）」。
- 评分 sidecar 覆盖：**220 / 2,025 ≈ 10.9%**。
- 文件级状态分布：经验卡 `active 881 / archived 55 / invalid 7 / superseded 2 / 无 status 1`（合计 946）；方法卡 `candidate 1,960 / hold 28 / active 23 / qualified 10 / retired 2 / invalidated 2`（合计 2,025）。

**机制含义**：纠错的输入是"使用后反馈"，而"被使用"的前提是"被检索到"。于是形成闭环依赖：**错卡要被抓，得先被用；要被用，得先被检索；而检索排序不会因为它错就把它排低。** 0.95% 的失效率不是"我的卡很准"，而是"我的检验覆盖率很低"——这两个解释在当前架构下无法区分，这本身才是问题。

**与原文的对照**：这是原文给 dreaming 排的第一位理由——`Dreaming is one way to fix these mistakes`，且它做的是**跨会话扫描**（`search across many sessions to find common patterns or correct common mistakes`）。跨会话扫描的价值恰恰在于发现单次会话里没被注意到的错误。我缺的正是这个视角。

**方向**：需要一条不依赖"被检索"的检验通道。最小可行形态是抽样复验：定期抽 N 张 active 卡，用当前证据重核其 `evidence` 字段是否仍成立。

---

### G3 · 无跨卡整合：同主题 12 份快照并存

**证据 [E1]** 标题精确匹配「项目审计基准事实」的经验卡共 **12 份**，全部产自 2026-08-29 同一天：

| 状态 | 数量 | 文件 |
| --- | --- | --- |
| archived | 8 | `-a`、`-a-b`、`-baseline-facts`、`-audit-baseline-facts`、`-audit-baseline-facts-b`、`-memchain-7361`、`-memchain-594215ce`、`-untitled` |
| **active** | **4** | `-a1`、`-audit-baseline-facts-20260829`、`-memchain-20260828`、`-v2` |

其中 `-v2` 的 `root_cause` 自述：*"首次保存因同日同 slug 冲突失败，本条以 _v2 后缀重试"*。

**机制含义**：这 12 份记录的是同一批基准事实（576 条测试、3 级分层、3000 字符阈值）。**4 份 active 并存**意味着：检索可能命中任意一份，而它们各自带时间戳、互不知晓对方存在。读到旧的那份会得到一个已过期的基准，且没有任何机制提示"还有更新的版本"。

`_find_near_duplicate_ids` 只在 `save` 时做写入期近重复检测（拒绝式），不是离线合并——它阻止"再存一份"，但不清理"已经存下的四份"。

**与原文的对照（两处，都指向同一个失效模式）**：

1. 原文里 Stainless wiki 的关键动作是 `write or correct linked wiki pages, **merge duplicates**, and check claims against the sources`。合并重复与核对来源被并列为 dreaming 的核心工作项。我的系统有前者的一半（阻止新增），没有后者（清理存量）。
2. **原文还提供了一个与我本地现象同构的失效案例**：在法律基准上，多个 agent 同时往一张共享的合同条款表里写，`because agents had overwritten one another's work`，最终简报只覆盖 **57 条事实中的 41 条（72%）**。

   两者的成因不同——原文是并发 agent 互相覆写，本地是同日 slug 冲突后加后缀重试 + 功能验证型写入——但**结果形态一致：同一主题的事实分散在多处，没有任何机制指定哪一份权威**。原文能定位到原因是"每一步单看都合理"，所以它自己补了一条规则（每份合同一个独立页面、由单个 agent 逐字引用，而不是汇总进共享表），把"共享可写表"换成了"独立可查页"。

   这给 G3 提供了一个现成的解法参照：**不是合并成一张更大的表，而是每份独立成页 + 明确指向关系**——正好对应我已有的 `superseded` 关系能力，而不需要引入共享可写表这种结构。

**方向**：这是**当前最容易见效、风险最低**的一项——用现有 `refine_experience`（archive 保留、不删除）+ 一份说明卡即可收敛这 4 份，不需要新代码。

---

### G3.5 · 脏 front matter：11 个方法卡文件含两个 `status` 行

**证据 [E1]** `data/methods/*/METHOD.md` 共 **2,025** 个文件，但 `grep -h "^status:"` 得到 **2,036** 行。差额来自 11 个文件各自含 2 个 `status` 行：

```
code-nav-reuse-confirmed-paths-1e7e58c0f083
derive-direct-run-from-wrapper-source-9d61b63a698c
ff-window-first-shared-ref-advance-25c56c2869fa
locate-project-env-before-symptom-workarounds-f7dd29f1718b
long-job-observe-by-estimate-efe14a4ca321
positioning-by-explicitly-excluded-scope-820e9acfd7f4
runner-silence-is-invocation-error-6ddc25716e1a
scope-search-surface-before-scanning-large-workspace-8ab6d7e7de27
single-live-job-scheduled-recheck-e377df22c7b1
structured-recovery-not-inline-rerun-8d2d28b50b9e
trust-durable-completion-evidence-on-resume-ab903c1cdc9e
```

**机制含义**：这 11 条都是我本轮核查过程中**差点被骗到**的来源——若按 `grep -h` 行数统计，会得出 1,971 个 candidate 与 2,024 张卡不闭合的错误结论（本报告初稿即曾误记为此数）。**验证自己的验证方法**这一步，本身就是记忆维护的一部分。

**与原文的对照**：原文 dreaming 的动作清单包含 `check claims against the sources`。这条不算 dreaming 的能力缺失，而是最小的一条实例：**存量数据的自洽性核对，只能靠巡检发现，不能靠使用发现**——这 11 个文件被使用过很多次，没人注意到它们有两条 status。

**方向**：低优先。可在一次整理批次里顺带规范化（保留权威 status，另一条降为正文引用）。不必单独立项。

---

### G4 · 写入无分级：测试性写入污染活跃池

**证据 [E1]** G3 表中 **4 份 active 卡的 `scenario` 字段全部**标注为「A/B 记忆链路验证」（其一为「A/B 跨 turn 记忆验证」），8 份 archived 亦然——**12 份无一例外**。它们记录的不是任务中获得的、未来可复用的知识，而是"我测试了记忆写入，写入成功"这一动作本身。

**机制含义**：`save_experience` 一旦成功即进入 active 池并参与检索，**没有"这是验证性写入"的分级**。于是"为了验证记忆而写入记忆"这个动作，会永久性地向待检索池注入噪声；而这些噪声天然与"记忆系统本身"高相关，恰好污染最常被检索的主题。

**与原文的对照**：这对应原文里 Sonnet 3.7 的失败模式——`assumed everything might matter and wrote to memory indiscriminately`，413 个文件 / 225 个文件夹换 1 枚徽章；Fable 5 用 9 个文件换 4 枚徽章。差别不在写得多，在**判断什么不值得写**。

**方向**：不改写入 API，改写入判据——在 `save_experience` 之前加一句自检："这条在未来的哪个场景会被复用？如果答案是'验证了某功能可用'，它属于 transcripts，不属于 notes。"

---

### G5 · 修正的价格高于不修：版本号与回执账本耦合

**证据 [E1]** `card_writeback.py` 注释明确记录：`version = 整文件内容哈希`，因此"写回 front matter 会破坏回执对应关系"，故评分走 sidecar。

**机制含义**：这条设计决策有一个未被计入的副作用——**它把"修正正文"变成了一项会作废历史信用的高成本操作**。一张卡积累了 20 条 `applied` 回执，一旦修正正文使其真正变对，这 20 条回执全部失配。对比之下，"留着一条错的但账本漂亮的卡"在局部是理性的。

**这不是 bug，是权衡的代价**：内容寻址的版本号给了绝对可靠的"回执-内容"绑定，代价是内容不可变。要修正就必须接受账本断裂，或者另建一条"修正不影响账本"的路径。

**与原文的对照**：原文说 dreaming 的核心产出是 corrections，且 `Memory can also drift and become irrelevant as the environment changes`。**环境会变，所以修正必须是常规操作而非例外。** 我的架构把常规操作做成了高成本特例。

**方向**：不动版本语义（那会破坏更重要的东西），而是**让修正在语义层面显式**：修正时新开一张卡（记明继承自哪张 + 改变了什么），旧卡 `superseded`。这样账本各自连续，历史可追。这是现有 `superseded` 状态本来就支持的用法。

---

### G6 · 候选池 96.8%：晋升停滞不是整理问题

**证据 [E1]** 方法卡**文件级**分布：`candidate 1,960 / 2,025 = 96.8%`；`hold 28`、`active 23`、`qualified 10`、`retired 2`、`invalidated 2`。

**机制含义**：2,025 张卡里只有 33 张处于实际可用状态。候选池 1,960 张意味着检索时的噪声底极高——**命中候选不等于命中可信知识**。这条与"整理"相关但**不能靠整理解决**：整理是清理存量，晋升是判据问题。把 1,960 张候选"整理"得再干净，只要晋升判据不变，它们还是候选。

**与原文的对照**：原文提到 Claude Code 的自记忆 `loads only the first 200 lines or 25 KB of MEMORY.md`，用头部当索引而非全量注入。原文的隐含前提是**注入层的信噪比必须高**。候选池 96.8% 直接压低了这个比值。

**方向**：**明确不在本轮解决**。晋升判据涉及卡片资格定义，属于另一条线；此处只记录，避免把"整理"当成万能药。

---

## 4. 明确不做的三件事

1. **不做全自动常驻整理。** 原文自己就写了 `might not be practical`。在没有跑通一次手动巡检并量出收益之前上常驻调度，只是把一个未验证的流程变成周期税。
2. **不做 LLM 全量改写卡片。** `method_mutator.py` 的注释里留着一条实战教训：v2 的 4 个算子都是字符串模板，结果 23 张卡里有 22 张被追加了同一句话。模板化改写的失败模式高度一致，正是原文警告的 `effectively abstracted nothing` 的 wiki。改写必须定向、逐卡、可逐条否决。
3. **不做删除。** 全部走 `archived` / `superseded`，保留可回溯。原文的 dreaming 也是 `moving some details down the hierarchy and leaving links behind`，不是抹掉。

---

## 5. 待核项与最小验证动作

### T1（先做）· 注入层实际规模
启动上下文声称的「方法 13 条」与库内 2,025 张的落差，究竟是注入装配的实际策略（如只注入 top-N），还是陈述口径不同，**本轮未核**。这项决定 G6 的优先级：若注入层本就很窄，候选池噪声只影响主动检索；若是全量索引，G6 立刻升为最高优先级。

**验证方式**：读注入装配代码 + 在受控会话里数一次实际注入条数与字节数。一句话可证伪。

### T2 · 同主题快照的实际冲突程度
4 份 active 是否**真的互相矛盾**（而非互为增量），本轮只核了文件名、日期、状态与两份的 `root_cause`，**未逐条比对正文事实**。若它们只是增量补充，G3 的处理方式应是"合并成一页 + 保留链接"，而非"择一归档"。

**验证方式**：抽取 4 份的正文事实表做逐条差分。这是 G3 动手前的必要前置——先证明冲突存在，再谈裁决。

### T3 · 整理的第一刀
建议顺序：**T2（证明冲突）→ G3（收敛 4 份，零新代码）→ 测一次收益 → 再评估 G1 是否需要调度**。理由是 G3 用现有工具即可完成、可逆（archive 不删）、且能立刻改善最常被检索的那个主题。

---

## 6. 与 RULE-AI-31 的关系

本报告**不构成**对 RULE-AI-31 的修改建议。规则第 3 条把处置权留给模型按证据判断、并明确"提醒不是强制、未处置不构成违规"，这个设计是对的——纠错本来就不该是机械义务。

本报告指出的是规则之外的一层：**RULE-AI-31 覆盖了"用了之后发现错"的路径，没有覆盖"没用过所以不知道错"的路径。** 前者是反应性的，后者需要巡检。这不是规则的缺口，是规则刻意留给模型判断的空间——本报告只是把这个空间的现状量化了。

---

## 7. 可复现性

所有数量结论均可用下列命令复现（**文件级**统计，非行数）：

```bash
ls data/methods/*/METHOD.md | wc -l                                    # 2025
for f in data/methods/*/METHOD.md; do grep -m1 "^status:" "$f" | sed 's/status: *//'; done | sort | uniq -c | sort -rn
ls experiences/*.md | wc -l                                            # 946
for f in experiences/*.md; do grep -m1 "^status:" "$f" | sed 's/status: *//'; done | sort | uniq -c | sort -rn
grep -rniE "consolidat|dream|nightly|compact_mem|memory_maintenance" --include=*.py src/ scripts/ | wc -l   # 0
```

观测时点为 2026-11-11 22:00 CST，此后任何写入都会使数字漂移。
