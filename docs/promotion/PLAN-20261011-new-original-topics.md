# LFL 原创图文第二批：选题与发布资格登记

记录时间：2026-10-10 晚；时区 Asia/Shanghai。此表只是编辑排期，不构成稿件审核或发布回执。目标每天至少争取 1 个真正新主题、争取 3 个；同稿在知乎和今日头条两个网站出现仍只算 1 个主题。

## D04 · LFL 审稿 PASS，头条已公开并完成图文验收

**标题**：AI Agent 把“练习”做成了真实操作：问题不只是模型不听话

- 主稿：`docs/promotion/20261010-lfl-daily-04.md`，配图 `fig16`、`fig17`、`fig18`
- 主要热点（原始材料）：Anthropic 10 月 9 日 https://www.anthropic.com/news/investigating-unintended-model-actions；HarnessSecurity-Bench 10 月 6 日 https://arxiv.org/abs/2610.07639；微软 HarnessAudit https://www.microsoft.com/en-us/research/publication/auditing-agent-harness-safety/
- LFL 独立审核：**PASS**。Web 审稿会话 `f72c7b3b-1d83-4db3-ba99-8f218141d122`，正文 SHA256 `34e880955d16640d0762b8039aa783651ec2dabbea7f3e541d7359defda4eb6f`，回执 `docs/promotion/receipts/20261010-daily04-audit.json`
- 今日头条新文章已提交 1 次：后台 PGC ID `7695059357230187008`，2026-10-10 23:29 起初显示“审核中”，23:45 独立复核转“**已发布**”；[真实单篇公开链接](https://www.toutiao.com/article/7695059357230187008/)正文与 fig16/17/18 三图已加载核验，回执 `docs/promotion/receipts/20261010-daily04-public-verified.json`，计 1 个新增公开主题，不得重复投稿
- 去重：区别于此前记忆、Method 自证、整体架构哲学三期；本篇聚焦真实外部动作、权限与结果验收

## D05 · 独立原创图文 LFL 审稿 PASS，头条已投稿审核中

**候选标题**：浏览器 Agent 的截图看着对，为什么交上来的表格可能全错？

- 一手材料：Odysseys2 十月公开的可浏览评测页 https://odysseysbench.com/v2/，100 个长网页任务、982 条rubric、2,480次打分尝试（**评测与论文状态、重复运行口径要单独核验**）。
- 平台发布前必需澄清：公开网页明确说明新评审**尚未经充分人工验证**，正式 Odysseys2 论文仍待公布，不能宣称同行评审结论，更不能把同一系统跨不同裁判评分差异当成同一维度能力退化。
- LFL 代码锚：`src/llm_loop/browser/errors.py` 多页面显式目标，`src/llm_loop/browser/cdp_action_host.py` 精确 DOM backendNodeId；与“结果落地文件验收”之间是不同层级，不能声称LFL已经参加Odysseys2或获得其成绩。
- 已完成正文：`docs/promotion/20261010-lfl-daily-05.md`，SHA256 `c712dc43a5e8198ed3491cc46e0b477f216339e46b6aa2b734252adfe0c5d9eb`
- 已完成原创配图：`docs/promotion/img/fig19-browser-grading.png`、`fig20-browser-artifact-gates.png`、`fig21-browser-receipts.png`，绘图脚本 `docs/promotion/figures/_d5.py`
- 状态：**LFL 独立只读审稿 PASS，四文件 SHA 精确匹配；今日头条于 2026-10-10 23:56 提交唯一新稿 PGC ID `7695067455462441507`，独立后台复核状态审核中，未公开验收，不计第2篇。** 审稿 session `776cbb14-cb07-4094-b621-823f4631b1b3`、回执 `docs/promotion/receipts/20261010-daily05-audit.json`；投稿前/后分别为 `20261010-daily05-toutiao-prepublish.json` 与 `20261010-daily05-toutiao-submission.json`。Odysseys2 仍属于项目方自披露，论文待公布、新评分方法人工验证不足，任何平台版本必须保留这一边界。不得重复提交同一ID

## D06 · 独立原创图文 LFL 审稿 PASS，尚未投稿

**候选标题**：AI 帮你搜到了答案，不代表它找全了证据

- 一手材料：Exa 10 月 8 日发布 ATLAS 搜索密集型 Agent 评测预览 https://exa.ai/blog/atlas-benchmark 。编辑必须区分实体发现、完整行字段、单个项目的不同 F1；其为预览与自发报告，不视为全面独立验证。
- LFL 代码锚：`src/llm_loop/tools/builtin/web_search.py` 存在 `[词典降级]` 与 `[降级记录]` 标注，不能把字典后端返回的近似答案宣传成实时网络搜索；阅读实际实现和测试，再确定稿件描述。
- 已完成正文：`docs/promotion/20261010-lfl-daily-06.md`，SHA256 `f5c985c937b33a99e126d19a191a35aea870fa3813a565693812cc32d02f12ce`
- 已完成原创配图：`docs/promotion/img/fig22-search-three-scores.png`、`fig23-search-fallback-flag.png`、`fig24-search-evidence-states.png`，绘图脚本 `docs/promotion/figures/_d6.py`
- 状态：**LFL独立只读审稿 PASS**（Web session `a5aeef60-1b0f-41da-88b1-4ce2671508df`，精确四文件SHA匹配，回执 `docs/promotion/receipts/20261010-daily06-audit.json`）；**尚未投稿、未公开**。Exa ATLAS 为供应商自报告，原始数据/金标准尚未开放；LFL的词典降级只是局部结果标注，不是全局搜索质量保证

## 所有新稿共用硬门

1. 真实源核验、仓库HEAD/发布标签/必要证据时点冻结，不复用旧稿过时统计。
2. 原创中文长文加至少2幅可验证配图，来源和版权清楚；含核心技术结论的图应由审稿员视觉复核。
3. LFL 独立审稿必须对确切正文SHA及每张插图SHA给出 **PASS**；REVISE 需最小改动、重算SHA重新复审。
4. 各渠道作者后台确认账户可发布且没有同标题/同正文；发布单条，不跨站把同稿当两篇，适度错时并尊重平台政策。
5. 提交后等待平台状态与公网实见，真实单篇URL+标题+正文+图片核验通过才算新发；审核中、草稿、提交成功未公开分别登记，不得冒充发布。
6. 不动两条旧重复文章；不执行仓库提交、合并、push、重启或清理已有dirty工作树。

## 班次运行规程（L1 提效防重复，2026-11-12 起生效）

来源：`docs/design/DESIGN-20261112-promo-shift-efficiency-v1.md`（grill 两轮审查冻结版）。本节为零代码流程规则，自 2026-11-12 晚班起对全部推广班生效，与「所有新稿共用硬门」并行适用；两者冲突时硬门优先。数值标注沿用设计文档 [实测]/[参数] 口径。

### D1 完成即停 + 降级链

1. 停止判据链（全满足才停）：**发布回执 ∧ 公网正文验收 PASS ∧ STATUS 落盘**。满足后立即 `update_goal complete` 并终止 run；禁止交付后追加审稿。
2. 公网验收失败：3 次指数退避重试（1+2+4 分钟窗口）[参数]；仍失败则降级为两级判据（冻结稿 SHA 与平台回执一致）+ STATUS 显式标注「公网未核项」，交下一班补核。不无限重试、不误停。
3. fail-closed（RULE-AI-30）：任一判据为空/无回执 = 未完成 = 继续任务；不得以「页面看起来已发布」替代回执。
4. 收口脚本幂等（台账 key 去重，重复执行不重复记账）+ 写后读校验；崩溃可从 receipts/ 恢复。

### D2 审稿分级 + 轮数预算 + 误判回路

1. P2 二分（白名单式，宁可误升不误降）：**P2a 强制处置** = 凡涉数字口径/事实结论/引文/标题标签规范/两类夸大；**P2b 措辞级** = 登记不阻断。
2. 审稿轮数预算 ≤3 [参数，依据 d80 实测 39 条 P2 全措辞级且 P0/P1 恒 0]：R1 全量审（完整 summary 原文入包）；R2 窄复审只送 diff+改动理由+相邻上下文，**附事实类全量清单兜底**（P0/P1/P2a 口径逐条核对）；R3 起只收 P0/P1，其余登记留档。
3. PASS 绑定新 SHA 时，窄复审仅对 diff 负责，不触发全量重审。
4. 分级误判检测回路：R2 发现 ≥1 条 P2a [参数，宁严勿松] → 记分级事故 + 当轮回全量模式 + 复查分级口径。

### D3 审稿包规范

1. 入包 = 完整 summary **原文**，禁用要点清单 [实测：要点清单曾造成 4 处「摘要无依据」假阳性]。
2. 核对清单引用**机检回执字段**，禁写死行数/字符数 [实测：写死数字是口径漂移源]。
3. 子代理输出硬约束：每条一行、限字数 [实测 d67/d68 验证有效]；稿件长度超子代理输入预算（31,698 字符 [实测]）时按预算切包，禁整包硬塞。

### D4 等待纪律

1. 粗等待替代轮询：`wait(job_id)`、`schedule` 事件谓词（job_terminal / review_terminal）。
2. 违规判据（机器可判）：**连续无进展查询 >3 次** [参数]（不以等待调用总数为判据，d80 口径含 spawn 启动动作的教训）。

### D5 shell 合并

1. 同阶段 grep/校验/派生统计合并为一次脚本调用；一次性脚本先落盘再执行（RULE-AI-36）。
2. 阶段目标：单班 execute_command ≤80 次 [参数]（d80 实测 310 次）。

配套：D6 收口单一脚本由 `scripts/promo_closeout.py` 承载（verify + STATUS + 台账 + goal 收口指引一次执行，幂等 + 双回执落 receipts/）；M1–M5 验收红线见设计文档 §6，自首个生效班次起采集。
