# 卡片生命周期治理（操作版）

- 生效：2026-10-12（Asia/Shanghai）
- 依据：`docs/design/DESIGN-20261012-card-lifecycle-governance-v1.md` §3（需求）与 §5（补充），本文是其**可执行落地版**；设计动机、拷问过程、背景症状见原设计。
- 管辖：`experiences/`（experience/lesson）与 `data/methods/`（方法卡）的创建、收口、失效、周检、写前量化。
- 不管：单张卡片内容的对错判断本身；推广文章的**选题与平台发布操作**。管：发布稿的**数值可核性**（R5 伴生 ledger 与审计覆盖）。

## 0. 单一真值与指称纪律

| 对象 | 真值 | 指称纪律 |
|---|---|---|
| 卡片 | `experiences/` + `data/methods/` | 按 stable id（`experience:<id>` / `method:<id>`）指称 |
| 定时提醒/班次 | `data/schedule.json` | 一律用「班次名+触发时间」（如"晚班 20:00"），**禁止硬编码 sid**。sid 会腐烂，班次+时间不会；引用前必读现值 |
| 周检产物 | `docs/governance/card-audit/YYYY-MM-DD.md` | append-only，按日一档 |

## R1 创建门

新建任何卡（experience / lesson / method candidate）**之前**：

1. **按问题类型检索**已有卡——用问题描述关键词（如"夸大 / 404 / 降级 / 截断"），不是卡名；`search_records(kind=experience)` 与 `search_records(kind=method)` 两个池都要搜，另查 `docs/` 是否已有散落的笔记教训。
2. 命中 ⇒ 二选一：
   - 新卡正文必须写**区别声明**（本卡比命中卡多管什么）；
   - 或改走对应池的 `record_use(use_decision=adapted)`——experience 池用 `refine_experience`，method 池用 `method_manage`——不新建。
3. 正文按卡类选**模板或形态**——是写法参考，不是准入条件：
   - **experience / lesson**（`save_experience`）：三段式（附录 A-1）——(a) 适用信号；(b) 不管什么（边界、易混邻卡点名、常见误用）；(c) 核验方法（1–3 个可执行核验点，附期望结果）。
   - **method 卡**（`method_manage(save_candidate)`）：正文至少一行非标题内容即可写入。六段式 `## Trigger / ## Discriminator / ## Short path / ## Stop conditions / ## Verification / ## Counterexamples` 是**可选排版**，缺节不再拒写（2026-10-20 起）。形态任选：提醒型（一句话）/ 索引型（指向规则、skill、脚本）/ 规程型（步骤确实不显然时）；详见 `docs/METHOD_CARD_WRITING.md`。
4. 核验结果 append-only：experience 写进正文「核验记录」段；method 采用六段式时写进 Verification 节，否则紧跟结论写一行核验记录。

> 存量卡不回填模板；由 R4 抽到时机会性补齐。
> 修正记录（2026-10-12）：设计 §5.1 原定统一三段式；I2 落地时 `method_manage` 实测拒绝三段式正文（contract violation: missing Trigger/Discriminator/Short path/Stop conditions/Verification/Counterexamples），证实 method 卡另有程序强制六段式契约，本文据此分卡类修正。
> 修正记录（2026-10-20）：写入边界取消六段式强制，只校验正文有可读内容；六段式降为可选排版（见 `docs/METHOD_CARD_WRITING.md`）。

## R2 收口转化（晚班 20:00 固定步骤）

晚班 SOP 在写当日 STATUS **之前**：

1. 扫当日工作笔记 / 会话记录，按判定式过筛：
   **教训 = 重做会避免一次已发生失败的运作规则**。
   - 感想、总结、"学到了"不算；必须能回答"下次遇到同场景，具体怎么做不同"。
2. 候选教训走 R1 同款检索去重；命中已有卡 ⇒ `record_use(adapted)` + 补充正文，不重复建卡。
3. 通过 ⇒ `save_experience(record_kind=lesson, verification_state=…)` 入库。
4. 当日 STATUS **必含一行**，三选一：
   - `教训入库：<id 列表>`
   - `教训入库：0 条`
   - `教训入库：未执行-<原因>`
5. **无快速通道**：先笔记后卡片。笔记是原料，卡片是入库品；当天没走完就第二天接，料不禁丢。

## R3 失效门槛分级（主阀门）

三轴分离，**禁止混判**。判定前先核该卡现势（`search_records` 查当前状态）——已失效的卡只补 `record_use`，不重复 invalidate（幂等）。

| 轴 | 触发判定 | 动作 |
|---|---|---|
| **事实轴**（前提对错） | **单一机械证据**即成立：<br>• URL 404（**双采样**，间隔 ≥ 10 分钟）<br>• API 字段不存在（附命令输出）<br>• 代码行为与卡片描述冲突（附 `文件:行` 摘录） | 立即 `invalidate(evidence_refs, note="前提错误：…")`；必要时落修正替代卡（method 用 `parent_ref`，experience 正文互指）。**可 `restore`，误伤保险** |
| **有用轴**（好不好用） | 维持原门槛：qualification fail，或 2 次 rejected use | experience/lesson：`invalidate` 或 `archive`；method：`invalidate` 或 `retire`（method 池无 archive，等义动作为 `transition=retire`，见下） |
| **门禁轴**（资格状态） | "缺第二任务类型 qualification" **不是**失效理由 | 仅影响 promotion，走 `method_manage(transition=…)`，不碰 invalidate/archive |

**任何使用现场**（record_use 时）发现前提不成立 ⇒ 当场走事实轴，不等周检。

**用后负反馈的任务收口时限（RULE-AI-29，2026-10-12；2026-10-18 撤销强制 record_use）**：负反馈闭环义务已升格为 SoT 行为规则（`docs/ai_rules.md` 规则二十九，EVO-20261012-19f88338）——触发三情形（不适配/误导/时效过期）分级处置（记录可选 / 修正首选 / 核验后弃用），修正与弃用的判定最迟当前任务收口前完成，明确判定当场处置；仅不适配且无证据表明卡片有错 → 无需动作、不升级弃用；会话后 ReflectionRun 扫描已留痕负反馈作兜底（模型义务在前）。本节 R3 三轴判定与之一致，冲突时以 SoT 为准。

**method 池 retire 治理（审稿 P1-3a 补）**：`method_manage` 转移词表为 `invalidate / retire / reopen`，**无 archive**。`retire` 用于「方法本身仍真，但不再适用或已被更好方法替代」，属有用轴动作，进入条件与有用轴相同（qualification fail 或 2× rejected use）；与 `invalidate`（前提错误，事实轴）区别在判定依据，两者均可逆——`retire` 可 `reopen`，恢复门槛同下方 restore。

**restore 恢复门槛（审稿 P1-5 补，两池一致）**：原失效证据被**机械复核推翻**（复测 URL 200 / 代码行为复核与卡描述一致 / 原判定命令输出被证伪），`note` 必须引用复核产物或回执路径；不接受"再试一次好了"。

判定入口用附录 B 决策树。证据必须机械可复核（命令输出 / HTTP 状态码 / 行摘录）；不接受"我觉得不对"。瞬态异常（网络抖动、超时）先复测再判，不把抖动当证伪。

## R3-bis qualification 通道（门禁轴落地，2026-10-30 打通）

**背景事实**（2026-10-30 核实）：method 池 1569 张 candidate 卡中，仅 60 张有 `qualification.jsonl` 回执，且皆为 `evaluator=model` 自评、多数 `verdict=not_evaluated`，其中 51 张 `promotion=pass` —— **这些卡至今仍停在 candidate**。即：写回执的能力一直存在，断的是「回执 → lifecycle 流转」这一执行环节。

> 修正记录（2026-10-30 晚，两次修正）：初版误写「全部 usage 账本为空」——实测 usage 账本为 store 级共享文件，当日实测 88 条/62 卡（54 张 candidate），初版按「每卡目录内」口径查了不存在的位置。二次修正：当日早版曾断言「结算回执与 usage 账本是两套互不相通的写入」——**亦误**：`settlement_submit` 的 kind=method 路径直调 `MethodStore.record_use`（`src/llm_loop/introspection/settlement.py:775`，自 `c72a615c`≈2026-10-16 起存在），结算回执**就是** usage 账本行；生产佐证：89 行中 53 行带 `run_id`/`attribution`（仅结算通道写入的字段）。真正缺的是：**0 条 rejected 提交**（applied 64 / adapted 11 / not_applicable 14 / rejected 0）——通道畅通，是流程层从未如实提交过 rejected。修订后的批量纪律（见下）据此重排通道优先级；rejected 缺料的抓手在收尾结算纪律，不在代码。

**通道三段式**（`scripts/qualification/method_candidate_qualification.py`，repo-owned）：

| 段 | 执行者 | 产出 |
|---|---|---|
| `pack` | 脚本 | 每卡一份评审包：卡正文 + status/usage/qualification 计数 + 评审题目 |
| 评审 | **独立子代理**（不参与卡的产出） | 逐卡结构化 verdict：`verdict`/`mechanism`/`task_benefit`/`promotion` + `claims`（逐条标 verified/unverified）+ `counter_case` |
| `verdict` | 脚本 | 校验后的 `method_manage` 调用清单（**proposal-only，脚本永不写库**） |
| 落库 | **持真人回合的父会话** | `method_manage(record_qualification)` + `method_manage(refine)` |

**为什么必须父子分工**：子代理的委派消息带 `program_origin=True`，`is_human_user_message` 为假 ⇒ `current_episode_ref()` 为空；而 `record_qualification` 对 `promotion=pass` 要求 `task_ref` 以 `episode:` 开头且独立于该卡 `source_episode_refs` —— **模型自造 ref 会被程序拒绝**。所以：子代理出结论，父会话落回执。

**独立性的真实含义**：评审子代理与父会话同模型时，独立性来自「独立会话 + 不得先读父会话结论」，不是来自模型差异。评审任务书必须显式写「主动找反例」并要求 `counter_case` 字段，否则产出的是背书而非结论。

**门禁（脚本侧，违反即拒收该卡）**：
- `method_ref` 必须在 pack 包内，否则拒；
- `verdict`/`mechanism`/`task_benefit`/`promotion` 必须在词表内，否则**整卡拒收**（不进任何调用清单）；
- `promotion=pass` 要求全部 `claims` 为 `verified`，否则拒（未经验证的建议不得晋升）；
- 无 `claims` 的结论拒收；
- `note`/`evidence_refs`/`task_type` 过 held-out 写侧防线后再产出入账清单。

**promotion → 流转映射**：`pass` → `transition=qualify`；`fail` → `transition=invalidate`；其余不产生流转动作。

**流转门槛现状**（`store.py` `_update_status_locked` 实证）：`candidate → qualified/active/hold` **无门槛**；`invalidated/retired` 需独立依据（一次 `verdict=fail` 回执，或 ≥2 个不同 episode 的 rejected 使用声明）；`teacher` 不可变。历史 `lifecycle_attempts.jsonl` 里唯一的 `cross_task_type_qualification` 阻断属**已废止的旧规则**，当前代码中该门槛不存在——不得据旧记录推断现行门槛。

**status 的实际效力边界**（`list()` 实证）：排序键是 `(score, coverage)`，**`status` 不进排序键**；status 只在分数与 coverage 完全打平时定先后（active > qualified > candidate > hold）。所以「qualify 改善召回」是错的说法——它只在完全打平时起作用。**提升召回靠的是把卡的正文、aliases、Trigger 写好，不是改 status 徽章。**

**批量处置的纪律（2026-10-30 修订：证据分流，使用优先）**：批量 `retire`/`invalidate` 按依据类型分流，单卡门槛与 store 门禁一致，不新增放宽：

- **机械证据通道（事实轴）**：脚本批采机械证据（URL 404×2 / 路径、字段、工具不存在 / 代码冲突摘录）⇒ 逐卡 `verdict=fail` 回执（claims=可复跑命令，evidence_refs=输出）⇒ 可批量 `invalidate`。机械证据即独立结论——可事后复跑，不需子代理逐卡评审。
- **使用负反馈通道（有用轴）**：≥2 个不同 episode 的 rejected ⇒ `retire`/`invalidate`（代码已支持）。使用即记账，负反馈到量自动获得处置资格。
- **独立评审通道降级为高频兜底**：只审「真实命中过」的卡——口径：usage 账本非空的 candidate（2026-10-30 实测 54 张，含 `docs/ASSESS-20260929-p5a-highfreq-triage.md` 的 25 张高频口径，为其超集），单批 1~4 张纪律照旧；**不承担清空 backlog 的义务**。
- **无机械证据且无使用记录 ⇒ 不处置，且不视为待清债务**：未被检索命中的卡无召回伤害、无处置价值。目标从「清空 candidate 队列」改为「真实命中的卡必有反馈闭环」。

**rejected 的语义边界与结算纪律（2026-10-30 补）**：`rejected` = 卡内容有误或实际误导了本任务（前提错 / 步骤错 / 边界声明失实）；`not_applicable` = 卡没错但不适配本任务。两者不得互换——把该报 rejected 的压成 not_applicable，会饿死有用轴唯一的低成本处置证据源（结算桥接已通：`settlement_submit` 直写 usage 账本）。每轮结算前自问一句「本轮哪张卡误导过我」：有则如实报 `rejected`（附 evidence_refs），无则不报、不硬凑。

每类机械判定必须配「应拦输入」实测测试；批量动作落 manifest（卡清单+依据+回滚路径），误伤走 `restore`/`reopen`（门槛见 R3）。`hold` 仍为「暂不启用」轻量标记、可批量使用，但它是排序末位徽章，不是召回优化手段。

**URL 双采样通道休眠注记（2026-10-30 复扫）**：全库 1633 卡仅 5 张含 `http(s)://`，全部为 `127.0.0.1:8xxx/9xxx` 本地端点或字面 `host` 占位符——**外部 web URL = 0，通道当前无适用对象**；usage 非空 54 张 pilot 亦 0 URL（`docs/governance/2026-10-30-mechanical-evidence-pilot.md`）。本地服务掉线属环境状态、非卡的前提错误，不喂本通道（防误伤）。唤醒条件：出现前提依赖外部 web URL 的卡；届时补「404 定罪 / 5xx·DNS·超时不定罪」两条行为测试。既有 16 条应拦测试保留为回归底线。

**门禁必须自己先证伪（2026-10-30 独立审查实测）**：首版门禁有三个**已复现**的绕过路径，独立审查（REVISE）抓出后已修：

1. `claims` 写成裸字符串（如 `["probably fine"]`）时，"非 verified 即未验证"的计数逻辑会把它漏过 → 门禁形同虚设。**修**：只有「dict + `status` 恰为 `verified` + claim 文本非空」才计为已验证，其余一律计未验证。
2. `promotion=pass` 与 `verdict`/`mechanism`/`task_benefit` 之间无一致性约束 → 「三项全 `not_evaluated` + `promotion=pass`」也能换来 qualify。**修**：`promotion=pass` 时 verdict 不得为 `fail`/`not_evaluated`，且 mechanism 与 task_benefit 必须同为 `pass`，否则整卡拒收。
3. `evidence_refs` 传裸字符串时被逐字符拆散成 list。**修**：字符串按单元素处理。

**教训**：门禁代码本身也有"看起来在工作"的漏洞，且漏洞形态正是"宽松解析"。因此——**每条门禁规则都要有一条"应拦输入"的实测测试**（本轮新增 6 条：裸字符串 claims / 缺 status 的 claim / 空 claim 文本 / verdict=not_evaluated+promotion=pass / mechanism≠pass+promotion=pass / evidence_refs 裸字符串），且修复后必须**用真实评审数据回归**，确认"漏洞堵住且真实数据行为不变"（本轮实测：修复前后 25 张卡的 transition 完全一致）。

**评审子代理的规模纪律**：单批 25 张或 5 张都会让子代理撞上下文窗口（实测 input 419K / 311K / 273K tokens 三档失败），**不是卡正文太大**（25 张卡正文合计仅 81KB），而是子代理自发"考古"——grep 到 `action_trace`/`process_versions`/`registry_*.py`/`store.py` 等与评审无关的模块。**修**：工具面收紧到 `execute_command` + `read_file`（不给 `search_files`，它极易诱发全库 grep），并在任务书里写死取证预算（总工具调用 ≤4~7）与禁区；分批按 1~4 张。中途 `agent_message` 纠偏来不及——纠偏只在下一个 step boundary 生效，子代理往往已冲到边界。**重试必须换任务书，不能照抄。**

**评审任务书必须落库（2026-10-30 Round 3 补）**：上述"重试必须换任务书"有个前提——**换出来的任务书得能找回**。2026-10-30 上午的 Round 2 实测：任务书从未持久化 ⇒ 每轮只能重建 ⇒ 重建稿未经验证 ⇒ 首波 8 个代理 **6/8 格式违约**（`mechanism`/`task_benefit` 写成自造短语，词表外 ⇒ 整卡拒收）。**修**：任务书落库为 `docs/governance/qualification-reviewer-taskbook.md`，含字面 JSON 示例 + 枚举值域 + 一致性红线；每轮开跑先读它，重试从它改，不再从零重建。**放行纪律**：先放 2 个试点代理，机械校验其回执（枚举合法 + 红线无违反）通过后再一次性放行剩余批次——试点不通过就换任务书，不带病放行。

**补派前必须查代理结算状态（2026-10-30 Round 3 实测，门禁第四例自证伪）**：本轮卡 10 在 12:05:17 的「回执文件覆盖检查」显示 MISS，此时**第一个评审代理仍在运行**（12:05:59 才落盘 05.json）——覆盖检查给的是「此刻文件状态」，不是「没有代理在写」。据此补派第二个代理 ⇒ 同一张卡两份回执（05.json / 10.json），harness 以 `duplicate_verdict_for_ref` 拒收合并（**门禁当场抓住**，rc=2）。**处置**：只落一条回执（10.json，promotion=mixed），删除冗余评审文件，harness 恢复 18 calls / 0 problems（rc=0）；两份回执结论略有差异（insufficient vs mixed）但都无流转动作，无安全影响，冗余件留档 `/tmp/r3_duplicate_05.json.bak`。**纪律**：补派前先取该代理的终态回执（`subagent_result`），确认它不会再写同一张卡；「覆盖检查 MISS」不足以作为补派依据。

## R4 风险导向周检

- **触发**：每周四 20:00 通知型提醒（先于周四 20:53 的周知识资产入库，产物当夜入库）。提醒以「班次名+触发时间」指称，现值查 `data/schedule.json`。
- **抽样池**（风险导向，总上限 8 张/周）：
  1. 近 14 天被 `record_use` 引用或工作笔记提及的卡——**全查**；**超过 8 张时按最近使用/提及时间新→旧保留 8 张，其余顺延至下周优先纳入**（溢出与顺延在当期产物头部如实记录）；
  2. (c)/Verification 段核验点最久未跑的卡——至多 3 张；
  3. 随机兜底——2 张。
  来源 2、3 在来源 1 之后的剩余配额内抽取，配额不足按 2→3 顺序取舍。
- **动作**：逐张跑 (c) 核验点 → 产物 `docs/governance/card-audit/YYYY-MM-DD.md`，每卡一行：
  `卡id | 核验点 | 证据摘录 | 结论 | 观察项`
  **硬格式：无证据摘录的"通过"行 ⇒ 本次审计整体无效，重跑。**
- **观察项三态出口（审稿 P1-3b 补）**：非空观察项必须标「保留 / 关闭 / 升级」之一——连续 2 周无新证据 ⇒ `关闭-无新证据`；出现机械证据 ⇒ 当场转 R3 事实轴（升级）；其余 `保留` 顺延下周。
- 发现事实轴问题当场走 R3；顺带补齐三段式。
- **走样检测**：连续 6 周审计"零发现且零失效" ⇒ 触发校准警报（审计在走过场，需重新校准抽样池或阈值）。
- **入库授权（审稿 P2-7 补）**：产物当夜 `git add docs/governance/card-audit/ && git commit` 的授权**承接「每周知识资产入库」提醒（周四 20:53 班次）的既有入库惯例**，且**仅限 `docs/governance/card-audit/` 审计产物目录**；不 push、不扩大范围——与 DESIGN §8 / PLAN §8「不执行仓库提交」按此窄口径并存。

## R5 写前量化（推广稿）

- **范围**：正文一切可核数值（计数 / 百分比 / 版本 / 日期 / 时长 / 大小），"约 / 近 / 超"同样算。
- **动作**：写作时同步写**伴生 ledger** `docs/promotion/YYYYMMDD-daily-NN-sources.md`，行格式：
  `正文数值 | 出处（文件:行 或 回执路径） | 观测时间`
  ledger **不进发布正文**（md2html 只转主文件，天然隔离）。
- **审计改法**：正则抽取正文数值 → 逐条对 ledger（缺行 = REVISE）→ 随机抽 2 条**实开来源**复核。审计从"验真相"降为"验格式 + 抽检"。

## 附录 A：正文模板（按卡类分）

### A-1 experience / lesson（`save_experience`）三段式

```markdown
## 适用信号
<出现什么情况/什么类型的坑，应当想起本卡>

## 不管什么
<边界、易混邻卡（点名）、常见误用>

## 核验方法
1. <可执行核验点：路径/命令/URL，附期望结果>

## 核验记录
- YYYY-MM-DD：<证据摘录> → <成立/失效>
```

### A-2 method 卡（`method_manage(save_candidate)`）六段式（可选排版，不强制）

```markdown
## Trigger
<出现什么情况应当想起本卡>

## Discriminator
<与相邻卡的边界：什么场景归哪张卡，点名 stable id>

## Short path
<命中后的最少步骤序列>

## Stop conditions
<什么情况下停止/放弃，不硬扛>

## Verification
1. <可执行核验点：路径/命令/URL，附期望结果>

## Counterexamples
- <反例：如果只按朴素做法会踩什么坑，实证案例>
```

> 映射关系（仅在采用六段式时参考）：三段式 适用信号→Trigger；不管什么→Discriminator；核验方法→Verification。Short path / Stop conditions / Counterexamples 是可选排版，不要求填写，留空不再是写入错误。

## 附录 B：失效决策树

```
发现卡片可疑
├─ 能给出机械证据（404×2 / 字段不存在 / 代码冲突摘录）？
│   ├─ 是 → 事实轴：invalidate(证据) + 需要则落替代卡 → 记录核验行
│   └─ 否 → 是"用了不好用"且有资格证据？
│            ├─ 是 → 有用轴：qualification fail 或 2× rejected use 门槛
│            └─ 否 → 不动卡，记入当期产物「观察项」列（三态出口见 R4）
└─ 仅涉及 promotion 资格 → 门禁轴：走 method_manage，不碰失效
```

## 附录 C：度量

| 指标 | 定义 | 健康线 | 异常含义 |
|---|---|---|---|
| M-阀门 | 月度 失效数 : 新建数 | > 0（有淘汰） | 比值 ≈ 0 且新建 > 0 ⇒ 阀门再次卡死 |
| M-形状 | 新建卡是否有可读结论（experience 三段式 / method 六段式仅为可选排版） | 报告值，无硬阈值 | 采用六段式时缺节仍被程序拒收；不采用不算失守。把 100% 当门禁会逼出为凑节而写的空话，与 2026-10-20 取消强制六段式一致 |
| M-证据 | 审计产物中带证据行占比 | 100%（否则审计无效） | 反复 < 100% ⇒ 周检走过场 |

## 附录 D：硬边界

- 卡片永不物理删除：两池 `invalidate` 均可 `restore`（门槛见 R3）；experience/lesson 的 `archive` 可恢复；method 池无 archive，等义动作为 `retire`，可 `reopen`（门槛同 restore）。
- 不回填存量卡模板（experience 三段式 / method 六段式），仅机会性补齐。
- 不改运行时代码与工具 Schema；纯流程 / 文档 / 提醒层。**注记（2026-10-30，GOAL-20261030-fc31abda）**：曾授权动运行时代码实现 settlement→usage 桥接；调研证实桥接已存在（`settlement.py:775` 直调 `MethodStore.record_use`，`c72a615c`），本 Goal 实际落地物为账本级测试（`tests/unit/test_settlement_usage_bridge.py`）与文档修正，**无运行时代码变更**，本边界不变。
- 不引入 wake 自动续跑；提醒一律通知型，产物留痕 + 班次承接。
