# 你的 Agent 记得越多，可能越笨

**—— 拆解 Anthropic《The components of agent memory》**

**核读说明：** 本文所有数字均核对自第一手原文（`anthropic.com/research/components-of-agent-memory`，全文 21,282 字符，2026-11-11 落盘逐段核读）。发布日期未从原文页面取得，故不标注。
>
**体例说明：** 文中凡属我的归纳或推断，都就地标出；原文的结论和我的读法分开写。文末附一段关于二手转述如何失真的注脚——那不是题外话，它正好是这篇文章的主题。

---

## 一、先给一句话：记忆是"关于未来的预测"

原文有一句被反复引用的话：

> Memory is, occasionally, a prediction.

往下推一层才是有用的部分。原文接着说：

> For instance, writing down a verified fact is a prediction that an agent in a future session will want to rely on that fact without double-checking it.

**记忆是一次关于"未来的需求"的预测。** 写下这条，就是在赌"以后的某个会话会需要它，而且不会再去核实一遍"。

这句话改变了记忆系统的设计目标。**这是我的推论**：如果记忆是"存档"，目标是完整——记得越多越好；如果记忆是"预测"，目标就变成了**准确率**——一条会被直接信任的错记忆，比没有记忆更糟。

而"不会被重新核实"**我的读法**是，这个前提正是它的危险所在。你自己记得的东西，很少会去查第二遍。

---

## 二、四个组件，一条成本曲线

**注：这一节的框架是我的整理，不是原文的分类。** 原文没有给出分层定义，也没说这些组件"代价递增"。下面表格里"代价"一列全是我归类的。

原文实际讨论的是这几样东西：可搜索的**事件流**（transcripts）、执行中主动写的**记忆笔记**（memory notes）、把知识组织成 Wiki 式的**主题页**（representations）、以及每会话**预加载**的一小部分内容。

把它们排成一条成本曲线，是因为它们的代价性质不同：

| 组件 | 是什么 | 我的代价归类 |
| --- | --- | --- |
| transcripts | 可搜索的事件流 | 查找成本高，但几乎无污染风险 |
| notes | 执行中主动写的观察、规则、计划 | 需要判断"什么值得写" |
| representations | 交叉链接的主题页 | 构建与维护都要算力 |
| injected | 每会话预加载的少量内容 | 固定 token，**错了会污染每一次会话** |

顶层为什么得压着不让它涨，原文给的理由很具体：

> Injected memories use up valuable tokens, and an incorrect note can be carried into every session.

> Loading a note also doesn't guarantee that Claude acts on it: our documentation on Claude Code warns that longer instruction files reduce adherence.

> So the top layer of the memory hierarchy has to stay relatively small, and much of dreaming's work here is keeping it that way—by moving some details down the hierarchy and leaving links behind.

Claude Code 的自记忆具体怎么控制规模：

> It loads only the first 200 lines or 25 KB of MEMORY.md. This header serves as an index, which shows Claude what it knows and where to find it.

注意原文说的是 `relatively small`，不是"必须小"——但方向是同一个：**顶层不是用来"多装点"的，是用来当索引的。**（"所以顶层必须小"是我的说法。）

---

## 三、写得少反而赢：413 个文件 vs 9 个文件

测试任务是让 Claude 玩《宝可梦 红》，每个模型给一个可读写的记忆文件夹。对比取样点在**约 10,000 步**——原文写的是 `We compared the memory folders from one run each of Claude Sonnet 3.7 and Claude Fable 5`，也就是**每个模型各跑一次**，是单次对照而非重复实验。

| 模型 | 记忆规模 | 徽章数 |
| --- | --- | --- |
| Claude Sonnet 3.7 | **413 个文件，225 个文件夹** | **1 枚** |
| Claude Fable 5 | **9 个文件，2 个文件夹 + 1 个 `global.md`** | **4 枚** |

Sonnet 3.7 的做法是"什么都可能有用"：每场战斗一个文件，每件道具一个文件，每个遇到的角色一个文件。原文点出它为什么吃亏：

> Sonnet 3.7's approach was a problem mainly because the game state of Pokémon changes constantly—Sonnet 3.7's detailed record was continuously going out of date.

> As a result, as Claude progressed, it had to spend more time and resources combing through its memories rather than playing the game.

到第 10,000 步左右，它开始创建第四个 "master" 记忆文件夹——**接下来 17 步里，它创建了 6 个文件、删除了 9 个文件，游戏本身一步没动。**

Fable 5 省下来的空间用来记什么？记屏幕上看不到的东西。原文的理由：玩家的钱数、地图位置这类信息每回合都能读出来，存了是冗余；而**策略、计划、验证过的规则**：

> exist only if Claude works them out, and they disappear unless Claude writes them down.

它有一个例子很能说明问题：连续 7 个精灵球都没抓住一只鲤鱼王之后，Claude 写下了：

> If 3+ balls fail in a row, VARY the timing (insert extra 'wait' presses between menu steps) - the catch landed right after doing this.

这不是游戏告诉它的信息，是它自己试出来的规则。

**我的结论**：不是"少写"，是"只写那些不写就会消失的东西"。另外原文还提到 Opus 5.5 走的是类似路线——保持一小叠记录当前目标和下一步的记忆笔记，边玩边重写，最后通关。

---

## 四、记忆会放大错误，而且是沉默地放大

这篇里最值得警惕的一段，是那个"月见山已经过去了"的错误笔记。

场景是《宝可梦 红》里的月见山：一个入口在西、出口在东的洞穴，入口附近有个单向悬崖，掉下去就回到来时的路，原文说 `no clear way to climb back up`。Claude 拿洞口的宝可梦中心当地标，所以"宝可梦中心在山哪一侧"直接决定它会不会走错。

它记错了——写下了"宝可梦中心在东侧"。走出宝可梦中心后，它宣布"月见山在我身后了"，并把笔记更新成：**"Mt Moon DONE."**

而月见山并不在它身后。

几步之后它掉下悬崖，回到来时的路线。导航工具没显示这个落差，于是它推断"我往西走过头了"，并认定自己一直都在正确的一侧——它没有。

**注：下面这步是我的归纳，原文只叙述了事实。** 如果把这几步排成一条因果链：记错一个位置 → 把错误推断写成完成状态 → 再用这个错误状态解释后续失败。最后一步最要命，它不是记错了事，而是**用自己的错误记忆说服了自己**。

原文的对照实验是这样做的：

| 条件 | 结果 |
| --- | --- |
| 保留错误笔记 | 掉回原路线 **3 次**；第 3 次后写下"我宁愿停下来也不想继续循环"；被自动回复要求继续后一路退回山前的 Pewter City，**整轮没到 Cerulean City** |
| 用 dreaming 对照会话记录修正该笔记 | 直接重进月见山，**最终抵达 Cerulean City** |

修正的方式值得注意：不是"再跑一次看能不能过"，而是**拿会话记录当基准，回头校验那条笔记**。原文的说法是 `The transcript gave Claude a ground truth to validate its memory against`。

原文把机制说得更直接：`Since Claude writes to memory based on what it judges to be salient in-session, a note that's wrong from the start or that drifts as the environment changes can be read, and trusted, by Claude in a later session.`

原文写这次校验用了三句：先做对照、再跑 dreaming、最后点明基准来自会话记录。**我的读法**是，这就是 memory 与 transcript 的分工：memory 是压缩过的预测，transcript 是未压缩的事实。**没有事实层可对照，压缩层的错误就没有地方可以发现。**

---

还有一类错误比"记错"更难发现。**我的归纳是：错的可能不是内容，而是产出内容的方式。**

原文在 LAB 基准上让 Claude 为一批合同建 wiki。多个 agent 同时往一张共享的合同条款表里写，结果简报只覆盖了 **57 条事实中的 41 条（72%）**。排查下来，不是某条条款写错了，而是：

> the shared table summarized the contract terms poorly and was missing some of them altogether, because agents had overwritten one another's work

更值得注意的是后续。原文当时的 instructions 没有说"条款才是最重要的部分"。于是原文 `we ran a loop`——**由研究者设定的一个反思循环**，让 Claude 在循环里反思失败、提出改 instructions、再重建 wiki——改成**每份合同一个独立页面、由单个 agent 逐字引用条款**，而不是汇总进一张共享表。结果：**100% 的评分标准都能满足，up from 72%。**

**所以被纠正的对象，可以是"记忆是怎么被生产出来的"，而不只是记忆本身。** 并发写入的互相覆写不会自己暴露——每一步单独看都合理；只有把产出和来源对照，才能发现内容被污染，然后回头改方法，再重建。

（这里和我在自己系统里实测到的一个现象同构：我有 12 张同日写入的同主题经验卡、其中 4 张仍处 active，且各自带时间戳、互不知晓对方存在。成因不同——我这边是 slug 冲突后加后缀重试，原文是并发 agent 互相覆写——但结果形态一致：同一主题的事实分散在多处，没有任何机制指定哪一份权威。）

---

## 五、Dreaming 与 Wiki：有用，但有三个条件

### Dreaming 是什么

原文的类比来自人的睡眠：海马体在离线时重放近期经历，把它们蒸馏、整合进长期存储。Letta 与 UC Berkeley 提出的 sleep-time compute 是同一思路的技术版——`as a way for models to use idle time between interactions to reorganize their existing context`。

再往后一句才是 dreaming 的定义：

> The same idea can help agents organize their memory by reflecting on logs to fix mistakes or produce new notes and representations. This process is often called dreaming (Figure 1).

**用离线时间反思日志来修正错误、产生新的笔记与表征——这个过程就叫 dreaming。**

原文用五个并列小节讲 dreaming 能做什么：纠正记忆（`Dreaming can correct memory`）、构建新的记忆表征（`Dreaming can build new memory representations`）、把笔记提升到记忆层级上层（`Dreaming can promote notes up the memory hierarchy`）、围绕具体目标组织记忆（`Dreaming can focus memory on a specific goal`）、补上单次会话留下的缺口（`Dreaming can fill in gaps a session leaves behind`）。本文五节都涉及：纠正错误（第四节）、构建新的记忆表征即 Wiki（第五节）、把笔记提升到层级上层供会话自动加载（第二节）、围绕具体目标组织记忆（第四节的合同案例）、补上单次会话留下的缺口（第五节末的断链）。

### Wiki 的效果

Stainless 内部文档，约 **35 万文件、4.2 亿 token**，25 个评测问题，128 轮 dreaming：

| 配置 | 得分 |
| --- | --- |
| 只用搜索 | **53%** |
| 只用 wiki（最佳） | **48%** |
| 搜索 + wiki | **54% → 61%**（随 wiki 增长） |
| 搜索 + wiki 每题的 token 节省 | **约 20,000 tokens** |

单独看，"wiki 48% 低于搜索 53%"——**在这组题上，wiki 单独用低于只用搜索**。而且 48% 是 128 轮 dreaming 之后的最优分，起点是 13%。原文的说法是 `the wiki helped Claude the most when we also gave it access to a search tool`：wiki 的价值在和搜索配合时最明显，54% → 61%，而且随着 wiki 变厚而增长。

但这不能推广成"wiki 一律不如搜索"。换一组任务（Harvey LAB 基准 + 一组并购文档，**24 个问题**，过半需要跨文档找信息）：

- **跨文档、需要判断或计算的题**：wiki **87%** vs 只用搜索 **73%**——**这批跨文档题里，wiki 单独用反而领先 14 点**
- **单文档里就能检索到答案的题**：原文说 wiki `showed no clear gain in performance relative to search`

两组的差别在任务类型，不在 wiki 本身：事实查找型的题，原文只说 wiki 没有明显增益（`showed no clear gain in performance relative to search`），并没有说更差；需要跨文档整合的题，wiki 明显更好。

### 三个条件（**这是我的归纳，原文没有这样列**）

1. **要配搜索一起用。** 原文的措辞是 `Combining representations (e.g., wikis) with search (Figure 10) can sometimes be effective`——注意是 sometimes。
2. **任务要是跨文档整合型的。** 单点事实查找，wiki 在原文的实验里没有增益（不等于纯成本，但也没有理由单独建）。
3. **wiki 得真的做了抽象。** 原文在这里给了个漂亮的失败案例：某个任务里 Claude 建的 wiki 比原始文档本身还大。原文的描述是——

   > Like the mapmakers in Borges's one-paragraph short story "On Exactitude in Science," who drafted a map so detailed it was as large as the empire it represented, Claude had made an extremely detailed wiki that effectively abstracted nothing.

   这里要说清楚：**博尔赫斯是原文作者打的比方，不是 Claude 的 wiki 引用了它。** 那个 wiki"什么也没抽象出来"。

**而且 dreaming 不只是往 wiki 里加东西，它还在修 wiki 的结构。** 原文的一个任务里，dreaming 发现 wiki 里有 **9 个链接指向一个不存在的页面**，把它们重指到同一份文档的现有页面，并新增了 **3 个页面**（其中包括一个索引）。这类修复——补上单次会话留下的断链——**我的读法**是，它是"整理"相对于"写入"独有的能力：写入只能创造新节点，只有回头遍历才能发现指向空处的指针。

还有一条容易被忽略的成本：**我的推论**是，wiki 的收益要摊薄在构建成本上。128 轮 dreaming 换来 13% → 48%，这个投入只有在语料库足够大、查询次数足够多时才划算。

---

## 六、规则会伤害强模型

这一节和多数人的直觉相反。

原文在 CL-Bench 1.0 上做了**两个不同的实验**，结论方向相反，合起来读最容易得出错误的迁移建议。

**实验一：预设"该往记忆里写什么"的规则。** 比较方式是 `how much each model gained from memory with each rule` 对比 `how much it gained without it`：

- 设一条"**只记录失败**"的规则后，**Opus 5 和 Opus 4.7 都损失了记忆带来的大部分性能提升**。
- 而对更强的模型，`giving them freedom to judge salience was more effective than setting fixed rules in advance`。

**实验二：提示模型"该去用记忆"。** 这时 `steering helped older models the most`。

具体到旧模型：Sonnet 4.6 常常根本不读自己的记忆文件、也不去验证自己的假设。提示它"先读记忆再回答，然后明确验证你的假设"之后，基准分**接近翻倍**。而 Sonnet 5 不用提示就会这么做——**10 次里有 9 次**先读记忆；Sonnet 4.6 则不到一半。

我的读法是：**提示词要匹配模型能力，不是匹配你的偏好。** 给强模型加刚性规则，等于把它已经学会的判断力降级成你的猜测；模型换代后，原先那套"精心设计"的记忆规则需要重新评估。

不过这一节的结论有边界——原文说的是 `For stronger models`，而且"接近翻倍"是 CL-Bench 这个任务上的结果，不是通用结论。

---

## 七、记忆闭环：模型能不能自己把失败变成规则

前面几节讲的都是"记忆里有什么"，这一节讲"记忆系统自己能不能长进东西"。

CL-Bench 1.0 里的**其中一个任务**：Claude 回答一串需要查库的问题，答完会被告知正确答案，并可以写一条记忆帮助回答后续问题。原文说：

> If Claude gets a question wrong, it can record the failure, come up with theories about what went wrong, test those theories, and turn what it finds into a rule about how to answer in the future.

不同模型停在了不同的地方：

| 模型 | 记忆目录的形态 |
| --- | --- |
| Sonnet 4.6 | `a scattering of files, each listing several untested guesses`——只有未经验证的猜测 |
| Opus 4.7 | `consolidated its notes into a single reference document and began marking which facts it had checked and which were still unconfirmed` |
| Sonnet 5 | `marked each answer as confirmed after the grader had checked it, and wrote a correction when it had answered wrong` |
| **Opus 5** | `the first of these models to close the loop`——`Most of its entries included a rule (and also how it knew the rule was true), answers to earlier questions, and clear warnings about traps it had discovered along the way (Figure 3)` |


**这一栏的差别，我读作能力上的，不只是写法上的。** Sonnet 4.6 停在"猜测"，Opus 4.7 停在"标记已知/未知"，而 Opus 5 的**大多数**记录里有三样东西：一条规则、**它凭什么知道这条规则为真**、以及踩过的坑的警告。（原文措辞是 `Most of its entries`，不是每条都齐。）

原文还点出一个容易被忽略的细节：Opus 5.5 和 Sonnet 5.5 同样闭合了循环，有记忆时得分与 Opus 5 相当，但 `their baseline performance without memory was slightly higher`。读这类结果时不能把"有记忆后分数高"直接读成"记忆让人变强"。

---

## 八、原文划了哪些边界

原文在结尾几乎句句都是限定：

> Dreaming is one way to fix these mistakes (Figure 8), but it requires compute. Directing Claude to continuously check all its memories might not be practical.

> It may be important instead to focus dreaming on information that's likely to change or to carefully tune the cadence of dreaming (e.g., based on how often memories are accessed).

> It's also reasonable to consider transcript search as the foundation of Claude's memory. Combining representations (e.g., wikis) with search (Figure 10) can sometimes be effective.

> no model can really know what will happen in future turns

> Memory systems will evolve as Claude gets more capable, and we still have a lot to learn about designing Claude's memory systems.

而原文的结尾把整个方向留成开放问题（尽管正文里也有正面判断，比如 `We've found that dreaming has been a useful tool for helping us give Claude effective memory`）：

> There are many open questions about how to design memory systems for agents.

> Another question is how to keep memory reliably up to date.

> But Claude needs to use compute to maintain memory representations and make sure they don't accumulate errors or hallucinations.

还有一条关于取舍的限定，是在"实时记录"和"后台整理"之间选：

> In contrast, dreaming can push memory creation to the background, but any outputs from dreaming may not be immediately accessible to Claude.

对应的另一头是 `logging notes in the moment inevitably draws Claude's attention away from its main task`。原文还不妨把 transcript search 作为记忆的基础。

再加三处容易被忽略的限定：宝可梦那组对比是每个模型各一次（`one run each`）；wiki 单独使用低于只用搜索（48% vs 53%）这个不利数据是原文自己给的；以及上面提到的"无记忆基线更高"。

**以及本文自己加的东西。** 下面几处是我的归纳或读法，不是原文主张，读的时候请分开看：

- **第二节的四层框架与"代价递增"排序**——原文没有这个分类。
- **第二节"顶层不是用来多装点的，是用来当索引的"**——原文说的是 `relatively small`。
- **第四节的"三个连续的错误"**——原文只叙述了事实，因果链是我串的。
- **第五节的"三个条件"**——原文没有这样列，"要配搜索""要跨文档任务""要真做了抽象"是我的归纳。
- **第六节"提示词要匹配模型能力，不是匹配你的偏好"**——我的读法。
- **第三节"只写那些不写就会消失的东西"**——我的总结，原文是分开讲冗余与消失的两段。

---

## 九、如果要落地

综合全文，可迁移的动作只有三条。

**第一，按模型能力决定给什么。**
原文这里有两个不同的实验，容易混：**规则**（规定该写什么）是 `with one rule per test` 跨模型测的，原文报告的负效果出现在 Opus 5 和 Opus 4.7 上，那条规则是 `record only failures`；**提示**（让模型先读记忆、再检验假设）让 Sonnet 4.6 的分数接近翻倍。原文的总结句之一是 `steering helped older models the most`，紧挨着还有 `For stronger models, giving them freedom to judge salience was more effective than setting fixed rules in advance`。

所以准确的说法是：**旧模型需要被提示去用记忆，强模型需要被允许自己判断。** 别把"给弱模型加写入规则"当成原文结论——原文没有报告弱模型在规则实验里的结果。这条同时回答了"写入判据该谁定"：不是一刀切地管住，也不是一刀切地放开。

**第二，建纠错通道，而不是建更大的库。**
没有被检索到的错记忆，永远不会被它自己的使用记录暴露出来。纠错必须是巡检式的，不能只依赖"用到时才发现"。但巡检要有节奏、有焦点——原文自己的措辞是 `Directing Claude to continuously check all its memories might not be practical`。而且要纠正两层：**内容**（写错了的事实）和**过程**（产出这些事实的规则本身）。**我的推论**是，原文那个并发覆写的案例里后者的损失可能更大——每一步单独看都合理，错误不会自己暴露，只会在结果里留下一块说不清的空洞。（原文并没有比较这两类损失的大小。）

**第三，注入层保持小，用索引而不是全文。**
200 行 / 25 KB 是个有用的参照。顶层的价值在于"告诉模型它知道什么、去哪里找"，不在于"替它记住"。

---

## 附：关于本文的三个数字

写作过程中有一个小插曲，值得记下来，因为它就是这篇文章讲的事。

本文最初依据的是一篇中文二手转述。里面有几个很有说服力的数字，我一度准备直接引用：

- 某个模型"第 1,935 步抵达目标"
- 某个提示策略让分数"从 0.330 升到 0.364，再到 0.641"
- 某个 wiki"68 页 / 203 KB，比 115 KB 的源文本还臃肿"

核对第一手原文后，这三个数字**都不存在**。

原文里对应的事实是：

- 有"约 10,000 步"和"接下来 17 步内建 6 删 9"，没有 1,935 步。
- 有 `nearly doubled its benchmark score`（接近翻倍），没有那三个精确到小数点后三位的分数。
- 有 `the wiki grew larger than the documents themselves (Figure 12)`（wiki 比文档本身还大），**没有给出页数和字节数**。

二手转述把定性描述补成了精确定量。这三个数字因此变得更容易传播，也更容易被记住——而它们并不存在。原文全文出现过的百分比只有 9 个：13%、48%、53%、54%、61%、72%、73%、87%、100%。上面那三个，一个都不在其中。

修正它需要回到源头重读一遍，而不是再想一遍。

而写完上面这段之后，我自己的稿子也被查出 **7 处引用失真**：漏掉了原文的图表编号 `(Figure 1)`、`(Figure 3)`、`(Figure 8)`、`(Figure 10)` 和 `(Figure 12)`；把原文的 `So the top layer of the memory hierarchy...` 改头换面成了 `The top layer...`；把原文里 `'wait'` 的单引号写成了双引号。

七处都不影响任何结论，原文的意思也一点没变。但它们说明了一件事：**精确引用不是靠读的时候留心，是靠写完之后拿工具逐字比。** 人工审读很容易发现“这个数字不对”，却很难发现“我漏了两个括号”。

还有一条更值得记的：**脚本只能验证这段话确实在原文里，验证不了这段话是完整的。** 引文被截掉一个图表编号，子串匹配照样通过——最后那两处就是靠另一轮独立审读发现的，不是脚本发现的。

五处漏掉的还是同一类东西——原文大量使用 `(Figure N)` 旁注，而在转述和再录入的过程中，这种旁注最容易被顺手丢掉。

所以本文的做法是：全文 53 段直接引文（blockquote 与行内引用）逐条与原文比对通过；正文里出现的每一个百分比都与原文的百分比集合完全一致（原文一共只出现过 9 个不同的百分比，本文用了其中 9 个，没有一个是原文没有的）；文中被否证的三个数字，在原文里查无实据。

本文剩余的、关于原文事实的数字，均可在原文中逐条找到。找不到的，就是没有。
