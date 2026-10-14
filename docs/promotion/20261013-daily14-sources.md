# 20261013 第 14 期科普 · 伴生来源 ledger（R5）

对象：`docs/promotion/20261013-lfl-daily-14.md`（标题《把程序从大脑降级为手脚：Agent 运行时的反直觉赌注》）
生成时间：2026-10-13 20:40-20:50（Asia/Shanghai）  仓库：~/Project/llm-first-loop-mirror
规则依据：`docs/promotion/PLAN-20261011-new-original-topics.md`（R5 伴生 ledger）+ `PLAN-20261012-I3-schedule-rebet.md`
原则：正文每个可核数值/机制断言在此登记「原文 → 来源 → 复测命令 → 结果」；**未核验项一律标 UNVERIFIED 并改写正文**，不得留待发布。

## A. 数值类（全部本地复测，2026-10-13 20:40）

| # | 正文断言 | 来源 | 复测命令 | 结果 |
|---|---|---|---|---|
| A1 | 版本 v0.6.32 | pyproject.toml:3 `version = "0.6.32"` | `grep -n '^version' pyproject.toml` | 0.6.32 ✅ |
| A2 | Python ≥ 3.13 | pyproject.toml:5 `requires-python = ">=3.13"` | `grep -n requires-python pyproject.toml` | >=3.13 ✅ |
| A3 | Apache-2.0 开源 | LICENSE 首行块 `Apache License / Version 2.0, January 2004` | `head -3 LICENSE` | Apache 2.0 ✅ |
| A4 | 2026-08-10 建库 | git 首提交 `2026-08-10` | `git log --reverse --format=%ad --date=short \| head -1` | 2026-08-10 ✅ |
| A5 | 2771 次提交 | git 提交总数 | `git rev-list --count HEAD` | 2771 ✅（20:40 复测；工作树有未提交改动，故正文标注了复测时刻） |
| A6 | src/llm_loop 169,911 行 | `find src/llm_loop -name '*.py' \| xargs wc -l` | 同左 | 169,911 ✅ |
| A7 | tests 196,403 行 | `find tests -name '*.py' \| xargs wc -l` | 同左 | 196,403 ✅ |
| A8 | 2026-09-07 审计快照约 7.5 万行 / 26 子包 / 460 测试文件 / 34 脚本 | docs/analysis/AUDIT-20260907-lfl-vs-peers.md:14 | `grep -n '7.5 万行' docs/analysis/AUDIT-20260907-lfl-vs-peers.md` | 一致 ✅ |
| A9 | 同业存在 1 万行级最小实现（pi） | AUDIT-20260907:30（peer 表 pi ~10K 行级最小 harness）+ :79（pi 1 万行 / 不做 harness 子系统） | `sed -n '30p;79p' docs/analysis/AUDIT-20260907-lfl-vs-peers.md` | 一致 ✅ |
| A10 | SWE-bench：114 实例 / 9 批次 / resolved 92.1%（报告自报口径；报告另称 resolved 105，正文未引该数） | docs/analysis/SWE-bench-official-summary_20260818.md:1,21 | `sed -n '1p;21p' docs/analysis/SWE-bench-official-summary_20260818.md` | 三个数字逐字一致 ✅；**但报告批次明细合计 112/106 与合计行 114/105/92.1% 不自洽**，正文已披露且明说不背书 |
| A11 | 114 只是 500 全量的一部分、重仓库未跑 | SWE-bench-official-summary:67 | `sed -n '67p' 同上` | 一致 ✅ |

**A 组口径纪律**：正文 A8/A6/A7 并列展示（7.5 万 → 169,911），并明写「一个月翻了一倍多」，未取区间端点放大，符合计划「区间不得取端点」硬门。

## B. 机制类（代码/README/规则原文）

| # | 正文断言 | 来源 | 结果 |
|---|---|---|---|
| B1 | 五步循环：消息进 → 理解 → 行动 → 真诚回答 → 记住 | README.md:5、README.md:95（LoopEngine 五阶段状态机） | ✅ |
| B2 | 三端接入 CLI / Web / 飞书桥 | README.md:9「三端接入（CLI / Web / 飞书桥）」；README.md:104「双端接入（Web + 飞书桥）：FastAPI :8903」 | ✅ |
| B3 | 浏览器 CDP：读操作与写操作分离、写操作单派发、程序不做模糊匹配/自动重试/完成判断 | browser_perceive / browser_operate 工具契约（只读感知 + 一次一个已决定 mutation + 不 fuzzy/rebind/retry/完成判断） | ✅（来源为运行时工具契约本身，非仓库文件） |
| B4 | EvidenceRef 的 freshness 只说「源版本新旧」，不等于「对当前任务仍然适用」 | read_evidence / read_file / source_synopsis 工具描述原文：「freshness/currentness 仅指 source 版本，不判断内容对当前任务是否适用」 | ✅ |
| B5 | 自主演进三道锁：① 纯建议通道 ② EVOLVE_LOCAL_EXEC 三级权限 ③ 完成登记 executor=human | README.md:98；docs/ai_rules.md:120 子规则 4（executor=ai / executor=human 两路登记；未验证须标 unverified） | ✅ |
| B6 | 涉安全边界/协议硬约束/数据完整性的演进「仅建议、等待人工执行」 | docs/ai_rules.md:120；README.md:98 | ✅ |
| B7 | SSRF：逐跳校验重定向 + curl 通道 `--resolve` 钉住已校验 IP 防 DNS rebinding | src/llm_loop/tools/builtin/web_fetch.py:12（模块说明）、:490、:562（`args += ["--resolve", resolve]  # P0-3`） | ✅（逐跳重定向校验的具体实现行由审稿人复核 B7b） |
| B8 | 会话 fork = 事件日志物理复制继承 + 源会话逐字节不变 | README.md:111、README.md:147（session-fork CLI） | ✅ |
| B9 | 事件溯源：事件日志为轨迹单一真相源、可回放对账、可回滚 | README.md:110（event-replay / event-verify / event-rollback） | ✅ |
| B10 | 唯一不让渡硬边界 = 不可逆删除/系统破坏；其余风险走带审计反馈闭环 | README.md:112「灾难性安全：唯一硬边界 = 不可逆删除/系统破坏，其余一切反馈放行」+ `data/audit/safety_blocks.jsonl` | ✅ |
| B11 | 第七节 8 个未结项与优先级 | AUDIT-20260907-lfl-vs-peers.md:70-80（四、风险与行动项）、:83-93（五、下一阶段路线）、:96-101（明确不做 6 条） | ✅ 审稿人已逐行复核通过；正文第 2 行优先级标 `P0*` 并注明为作者归并读法；ROADMAP-B-20260814.md 不含这些优先级，正文与 footer 均不再引它 |

**B 组一处已改写的事实纠偏（留档）**：初稿写「灾难性安全硬阻断不可被审批放行」。核 README.md:114 原文即写「灾难性安全硬阻断不可审批」，而代码侧（src/llm_loop/tools/safety.py:11、tools/registry.py:324、tools/builtin/execute_command.py:228）确有 escalation_request → web 人工审批 → 一次性令牌定向放行闭环，两者口径不一致（README 疑为陈旧）。该表述过强，已在正文改为 B10 的 README.md:112 口径；README 与代码的这一冲突建议单独立项，本文不断言。

## C. 观点类（不要求仓库背书，但必须在正文标注）

- 第三节「程序越笨，Agent 越聪明」的因果叙述、第六节未来趋势判断、文末结论 → 正文已显式标注「作者判断/观点，非项目官方立场」，footer 亦重申。
- 第四节「人设计判据、模型填语义」的解释路径 → 属解读，非引用。

## D. 交独立审稿人复核项（我未逐字核到行，交由 PASS/FAIL 判定）

- D1：B7b——web_fetch.py 是否确有「逐跳重定向重新解析并重新校验内网地址」的独立实现（不能只凭模块注释）。
- D2：B11——第七节表格 8 项与 AUDIT-20260907「四、风险与行动项」的逐项对应与优先级是否一致。
- D3：图片 fig41 / fig42 的数值与断言是否与正文一致、图注是否可读无残段。
- D4：正文 3.2 与第六节的工具能力边界描述（浏览器 CDP 三条不变量、EvidenceRef 的 freshness≠适用性、SSRF 逐跳校验）是否与工具契约及代码一致。
- D5：标题长度 ≤30 字、无抽象词开头；正文是否含 AI 辅助声明与事实依据 footer。

## E. 门禁自检（发布前，2026-10-13 20:50）

- md 图片数 2 == HTML 内图注锚点数 2；`grep '<p>fig'` = 0 残段 ✅
- HTML：`<h2>` 9 个、`<h1>` 0 个（标题仅进标题栏，不在正文重复）✅
- 标题《把程序从大脑降级为手脚：Agent 运行时的反直觉赌注》27 字 ✅
- footer 含事实依据 + AI 辅助声明 ✅

## F. 发布前复算回执（2026-10-13 20:46，发布者会话有 shell，独立审稿子代理无 shell 未能自算）

| 项 | 命令 | 实测输出 |
|---|---|---|
| A4 | `git log --reverse --format='%ad' --date=short | head -1` | `2026-08-10` |
| A5 | `git rev-list --count HEAD` | `2771` |
| A6 | `find src/llm_loop -name '*.py' -not -path '*__pycache__*' | xargs wc -l | tail -1` | `169911 total` |
| A7 | `find tests -name '*.py' -not -path '*__pycache__*' | xargs wc -l | tail -1` | `196403 total` |

审稿子代理第 2 轮遗留项处置：A4-A7 由本会话按上表命令实跑复算（子代理侧为 UNVERIFIED）；ledger A9/A10/B11/B 组纠偏/D4 已按子代理指正改写；HTML 已用最新 md 重新合成并复跑 E 组门禁。

## G. 发布结果回填（2026-10-13 21:05）

- 知乎：已发布并公网验收 PASS（p/2093444801823760655，status=200、h1=1、h2=9、两张 zhimg 图、AI 声明 footer、审稿改写 4 处全部在公网正文命中）。
- 头条：20:53 提交、pgc_id=7696133427334070825、平台状态=审核中；20:53 公开 URL 访问被重定向回首页，公网回读判 FAIL_NOT_PUBLIC，已排 +13 分钟一次性提醒复核（不以后台状态冒充公网通过）。
- 话题标签：**tags=0**，两平台均未满足「≥1 个话题标签」门禁。头条无控件；知乎候选仅书籍/园区类，主题不符，按纪律不硬塞。此项为已知未满足门禁，不是遗漏。
- 正文/HTML 最终 SHA256：md=c5c84929fdf474f929e975d00e917d2e02c31b4e30c578f5e09c5270b8135cb0，html=d6e3bcbc717a2528da3e009d11a5296dfcffbc77197d3e3e1de3449f7f93883f。
- 头条补充（21:05）：审核通过并已公开，`https://www.toutiao.com/article/7696133427334070825/` 回读 PASS —— h1 正确、正文 5864 字 / 118 段、9 章节全命中、两图以 1000x700 与 1000x640 真实尺寸加载、两条图注命中、审稿 4 处改写在公网可见。上一条 FAIL_NOT_PUBLIC 是 20:53 审核中的真实观测，不是最终状态。
