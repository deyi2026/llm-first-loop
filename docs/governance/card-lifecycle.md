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
3. 正文按卡类走**不同模板**，缺一不建：
   - **experience / lesson**（`save_experience`）：三段式（附录 A-1）——(a) 适用信号；(b) 不管什么（边界、易混邻卡点名、常见误用）；(c) 核验方法（1–3 个可执行核验点，附期望结果）。
   - **method 卡**（`method_manage(save_candidate)`）：程序强制六段式 `## Trigger / ## Discriminator / ## Short path / ## Stop conditions / ## Verification / ## Counterexamples`，缺任一节**写入即被拒**（附录 A-2）。三段式内容映射：适用信号→Trigger，不管什么→Discriminator，核验方法→Verification，其余三节按语义补齐。
4. 核验结果落进正文「核验记录」段（experience）或 Verification 节（method），append-only。

> 存量卡不回填模板；由 R4 抽到时机会性补齐。
> 修正记录（2026-10-12）：设计 §5.1 原定统一三段式；I2 落地时 `method_manage` 实测拒绝三段式正文（contract violation: missing Trigger/Discriminator/Short path/Stop conditions/Verification/Counterexamples），证实 method 卡另有程序强制六段式契约，本文据此分卡类修正。

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

### A-2 method 卡（`method_manage(save_candidate)`）六段式（程序强制，缺节即拒）

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

> 映射关系：三段式 适用信号→Trigger；不管什么→Discriminator；核验方法→Verification。六段式多出的 Short path / Stop conditions / Counterexamples 是 method 卡的程序契约要求，须按语义补齐，不可留空。

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
| M-形状 | 新建卡模板完整率（experience 三段式 / method 六段式） | 100% | < 100% ⇒ 创建门失守；method 缺节程序即拒收，实际风险集中在 experience 侧 |
| M-证据 | 审计产物中带证据行占比 | 100%（否则审计无效） | 反复 < 100% ⇒ 周检走过场 |

## 附录 D：硬边界

- 卡片永不物理删除：两池 `invalidate` 均可 `restore`（门槛见 R3）；experience/lesson 的 `archive` 可恢复；method 池无 archive，等义动作为 `retire`，可 `reopen`（门槛同 restore）。
- 不回填存量卡模板（experience 三段式 / method 六段式），仅机会性补齐。
- 不改运行时代码与工具 Schema；纯流程 / 文档 / 提醒层。
- 不引入 wake 自动续跑；提醒一律通知型，产物留痕 + 班次承接。
