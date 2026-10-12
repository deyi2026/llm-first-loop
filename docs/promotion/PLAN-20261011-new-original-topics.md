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
