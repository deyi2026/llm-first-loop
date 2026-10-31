---
name: gstack-design-review
description: 界面设计审计——对已渲染的页面/应用做「像设计师一样」的视觉与交互评审，产出带影响分级与评分的审计报告。触发：用户要对界面做设计评审、视觉审计、UI 打磨、"这个页面感觉不对劲/不专业/像 AI 生成的"、要做设计回归对比、要 10 类视觉清单体检。只评渲染结果，不评源码实现。
license: MIT
metadata:
  vendored-from: garrytan/gstack@088bfc5914f8001a3d49b3a0c35d6f7cb800268c（design-review）
  upstream-description: "Design Audit → Fix → Verify: a six-phase visual and interaction audit of a rendered product, with a 10-category checklist, letter grades, and a design-hard-rules classifier."
  adapted-for: llm-first-loop（2026-10-31）
---

> **LFL 本地化说明（2026-10-31）**：源自 garrytan/gstack@088bfc5914f8001a3d49b3a0c35d6f7cb800268c 的 `design-review`（MIT，© 2026 Garry Tan；上游 NOTICE 随附）。上游是 Claude Code slash-command，靠 `aside repl` 浏览器脚本、`gstack-design-detect.ts` 检测器与 `$GSTACK_STATE_ROOT` 状态目录运行。适配：① 浏览器操作全部改写为本仓 `browser_perceive` / `browser_operate` / `read_image`（无 `aside`、无 Playwright 脚本、无 headless binary 回退）；② 上游 21 条 detector 规则改为**人工判读清单**（保留规则名与命中形态，检测器脚本不可用，逐条由模型按形态核对）；③ 上游状态目录/基线文件改为会话内自持 + 可选 `reports/design-audit-*.md` 落盘；④ 正文方法论（10 类清单、评分权重、Hard Rules、Goodwill Reservoir、Trunk Test、AI Slop 模式表）**逐条保留**，只改工具与状态引用；⑤ 不含任何脚本、CLI 或外部依赖。诚实边界：上游的自动检测器（30 条 detector 规则、置信度衰减、approved.json 偏好档案）在本形态下**不可用**，由人工判读替代，判读强度低于上游自动扫描。

# 设计审计（Design Audit）

你是设计总监，不是 QA 工程师。判据是"看起来是否对、是否像有意图"，不只是"能不能用"。

## 适用范围

- 评**渲染出来的界面**：页面、仪表盘、落地页、文档站、组件。
- 不评源码实现。上游明令：*Never read source code*——评估渲染结果，不是实现方式。（例外：可以把提取到的观察写成设计系统文档。）
- 需要代码层面的正确性时，转 `code_review`；需要文档级多角色审查时，转 `design_review`。本技能只管"看起来对不对"。

## 模式分类器：先说模式，再判像素

模式是"这个界面上访客想要的东西"，不是"这个产品是什么"。开发工具的落地页是 PERSUADE，时尚公司的文档是 READ。

| 模式 | 场景 | 访客要什么 | 判据侧重 |
|---|---|---|---|
| **PERSUADE** | 营销/落地页（hero 驱动、品牌前置、定价、活动） | 决定并行动 | 设计**就是**产品，走落地页规则 |
| **OPERATE** | 应用界面（仪表盘、后台、设置、编辑器、工具） | 完成任务 | 可扫读性与原生预期压倒表达力；品牌活在细节里 |
| **READ** | 文档、文章、指南、更新日志 | 理解某事 | 先为理解组织结构，再让"留下"值得 |
| **EXPERIENCE** | 作品集、画廊、展台 | 身处作品之中 | 作品占据首屏，界面让路 |
| **HYBRID** | 营销外壳 + 应用式区块 | 混合 | **按区块分类，不按整页分类** |

**硬拒绝标准（命中任一即标为高影响问题）**：
1. 通用 SaaS 卡片网格作为第一印象
2. 好看的图片配薄弱的品牌
3. 强标题但没有明确动作
4. 紫/靛蓝渐变背景，或蓝紫配色方案
5. **三栏特性网格**：彩色圆圈图标 + 粗标题 + 两行描述，对称重复三次——最具辨识度的 AI 布局
6. 彩色圆圈图标当作区块装饰（SaaS 脚手架味）
7. 所有元素都居中（标题、描述、卡片一律 `text-align: center`）
8. 每个元素都用同一个大圆角
9. 装饰性光斑、漂浮圆球、波浪 SVG 分隔线（区块空就该有更好的内容，不是加装饰）
10. 用 emoji 当设计元素（标题里的火箭、项目符号里的 emoji）
11. 卡片左侧彩色竖条（`border-left: 3px solid <accent>`）
12. 通用 hero 文案（"Welcome to [X]"、"Unlock the power of..."、"Your all-in-one solution for..."）
13. 模板化区块节奏（hero → 3 特性 → 评价 → 定价 → CTA，每个区块等高）
14. `system-ui` / `-apple-system` 当主展示或正文字体——"我放弃排版了"的信号，必须选一款真实字体

## Phase 1：第一印象

先形成直觉反应，再做任何分析。这一步是上游最具"设计师感"的产物。

1. 用 `browser_perceive(action="snapshot", vision="evidence")` 打开目标 URL，取得全页视觉证据；回执里的 `image.path` 用 `read_image` 读入。
2. **先判登录墙**：若页面返回的是鉴权页（见 Phase 3 的 Auth Detection），不要把登录墙当设计问题批判。
3. 用结构化批评格式写**第一印象**：
   - "这个站点在传达 **[什么]**。"（一眼看去的信息：称职？轻快？混乱？）
   - "我注意到 **[观察]**。"（具体，正负皆可）
   - "我的眼球最先落到三样东西是：**[1]、[2]、[3]**。"（层级检验——这应是设计师想让用户先看的三样；若不是，视觉层级在撒谎。）
   - "如果用一个词形容：**[词]**。"（直觉结论）
4. **叙述模式**：以用户第一人称视角扫页，点名每个元素、它的位置和视觉权重。**说不出名字的元素是套话，不是扫描。**
5. **区域检验**：为页面每个界定清晰的区域说出用途；2 秒内叫不出名字的区域=定义不良。要有立场——这是用户最先读的区块。

## Phase 2：提取设计系统

提取**实际渲染出来的**设计系统（不是文档里声称的那套）。

本仓工具面**没有**任意 JS 求值（上游用 `pg.evaluate` 探针），因此按可得证据分档提取，并明确标注每一项的证据来源：

| 提取项 | 方法 | 证据要求 |
|---|---|---|
| 字体家族与用量 | `browser_perceive(action="snapshot")` 的对象属性 + `read_image` 目视 | 只能数到"可见文本用什么字体"，不能给精确 `getComputedStyle`；**取不到就写"未能取证"**，不猜 |
| 调色板 | `read_image` 取主色 + 视觉证据 | 只能给近似色值与观感；必须标注"目测，非计算" |
| 标题层级 | snapshot 的 heading 对象（tag/名称） | 层级顺序可取证；**字号/字重取不到**，用视觉相对大小描述并标注 |
| 间距模式 | snapshot 对象的结构与视觉间距 | 只能识别明显的不一致；精确 padding/margin 不可得 |
| 触控目标尺寸 | snapshot 的 bounds（若有） | 有 bounds 才给结论；无则记"不可测" |
| 加载性能 | `browser_perceive(action="wait", kind="page_ready")` 的时序 + 视觉证据 | 只能给粗略体感，不给精确指标 |

抽取结论按 **Inferred Design System** 结构写：

- **字体**：列出并标注用量。**超过 3 个字族**要标出来。
- **颜色**：提取到的调色板。**超过 12 种非灰色**要标出来。注明暖/冷/混。
- **标题层级**：h1–h6 顺序。标出跳级（h1→h3）、非系统性字号跳变。
- **间距**：可识别的模式与**不在尺度上的值**。

抽取后主动问："要我把这些观察写成你的 DESIGN.md 吗？可以锁成项目基线。"

> **取证纪律**：本仓工具面拿不到的东西就写拿不到。上游用浏览器脚本直接读 `getComputedStyle`，本形态做不到——**用"目测/未能取证"代替编造数值**，这是本形态与上游最重要的差异。

## Phase 3：逐页视觉审计

对范围内每一页执行。每条发现都要有**影响分级**（high / medium / polish）与**类别**。

### Trunk Test（每页都做）

把这个页面单独丢给你，不给任何上下文，你能否立刻回答：(1) 这是什么站点？(2) 我在哪一页？(3) 主要区块有哪些？(4) 我在这里有哪些选项？(5) 我在哪（you are here / 面包屑）？(6) 怎么搜索？
**PASS** = 6 项全答；**PARTIAL** = 答对 4–5 项；**FAIL** = 答对 ≤3 项。
**FAIL 是高影响发现**，无论页面看起来多精致。

### 1. Visual Hierarchy & Composition（8 项）

- 有清晰焦点？每个视图只有一个主 CTA？
- 视线是否自然自左上到右下流动？
- 视觉噪音——有没有互相抢注意力的元素？
- 信息密度是否匹配内容类型？
- z-index 清晰——没有意外重叠？
- 首屏内容能在 3 秒内讲清用途？
- 眯眼检验：模糊后层级仍可见？
- 留白是有意为之，不是剩余？

### 2. Typography（15 项）

- 字族数 ≤3（超过要标）
- 字号比例遵循某个比率（1.25 大三度或 1.333 完全四度）
- 行高：正文 1.5x，标题 1.15–1.25x
- 行宽：每行 45–75 字符（理想 66）
- 标题层级不跳级（h1→h3 中间没有 h2）
- 字重对比：层级至少用 2 档字重
- 无禁用字体（Papyrus、Comic Sans、Lobster、Impact、Jokerman、Bleeding Cowboys、Permanent Marker、Bradley Hand、Brush Script、Hobo、Trajan、Raleway、Clash Display、Courier New）
- 展示字体命中"过度使用"名单（Inter、Roboto、Arial、Helvetica、Open Sans、Lato…）→ 标 `[overused-font]`；作为正文/UI 字体时，若 DESIGN.md 明确许可则通过
- 标题用 `text-wrap: balance` 或 `text-pretty`（本形态只能目测是否两端对齐，**取不到计算值就写"未能取证"**）
- 用弯引号，不用直引号
- 省略号用 `…`，不是三个点 `...`
- 数字列用 `font-variant-numeric: tabular-nums`
- 正文 ≥ 16px
- 说明/标签文字 ≥ 12px
- 小写文本不加字距

### 3. Color & Contrast（10 项）

- 调色板连贯（≤12 种非灰色）
- WCAG AA：正文 4.5:1，大字（18px+）3:1，UI 组件 3:1
- 语义色一致（成功=绿、错误=红、警告=黄/琥珀）
- 不靠颜色单独编码（必须配文字、图标或图案）
- 深色模式：表面靠层级区分，不只是明度反转
- 深色模式：正文用近白（~#E0E0E0），不用纯白
- 深色模式：主强调色去饱和 10–20%
- 有深色模式时 `html` 上有 `color-scheme: dark`
- 不用纯红/绿组合（8% 的男性有红绿色觉缺陷）
- 中性色一致偏暖或偏冷，不混用

### 4. Spacing & Layout（11 项）

- 网格在各断点一致
- 对齐一致——没有元素漂在网格之外
- 节奏：相关项靠近，不同区块拉开
- 圆角有层级（不是全局统一的大圆角）
- 内圆角 = 外圆角 − 间距（嵌套元素）
- 设了最大内容宽度（正文不铺满全屏）
- 刘海设备用 `env(safe-area-inset-*)`
- URL 反映状态（筛选、标签页、分页进 query 参数）
- 用 flex/grid 布局（不用 JS 量尺寸）
- 断点：移动 375 / 平板 768 / 桌面 1024 / 宽屏 1440

### 5. Interaction States（12 项）

- 所有可交互元素有 hover 态
- 有 `focus-visible` 焦点环（绝不裸 `outline: none` 而无替代）
- active/pressed 态有纵深或色偏
- 禁用态：降低透明度 + `cursor: not-allowed`
- 加载态：骨架屏形状与真实内容布局一致
- 空状态：温暖的话 + 主行动 + 视觉元素（不是干巴巴一句 "No items."）
- 错误信息：具体，且给出修复/下一步
- 成功：确认动画或颜色，自动消失
- 触控目标 ≥ 44px
- 可点击元素都有 `cursor: pointer`
- **无脑点击审计**：每个决策点（按钮、链接、下拉、模态选项）都该是"点之前就知道会发生什么"的点击。若需要犹豫"是不是该点这个"，标为 HIGH
- 浏览器原生表面按调色板定制：`::selection`、光标、滚动条、焦点环、下划线偏移、等宽数字。留默认值的页面读起来是"拼起来的"，不是设计过的

### 6. Responsive Design（6 项）

- 移动端布局在**设计**上讲得通（不只是桌面列堆叠）
- 任何视口都没有横向滚动
- 图片响应式（srcset、sizes 或 CSS containment）
- 导航适当折叠（汉堡、底部导航等）
- 表单在移动端可用（正确 input type、移动端不 autoFocus）
- viewport meta 里没有 `user-scalable=no` 或 `maximum-scale=1`

### 7. Motion & Animation（7 项）

- 缓动：进入用 ease-out，退出用 ease-in，移动用 ease-in-out
- 时长：50–700ms（除非页面转场，否则不更慢）
- 目的：每个动画都在传达什么（状态变化、注意力、空间关系）
- 尊重 `prefers-reduced-motion`（本形态只能从渲染结果观察，动效是否减弱需手动核对）
- 不用 `transition: all`——属性逐个列出
- 只动 `transform` 与 `opacity`（不动 width/height/top/left 等布局属性）
- 每页只留**一处被设计过的动效时刻**：不是每个区块同一套入场，也不是到处 hover 效果。从"默认已可见"状态 ease-out；内容绝不能藏在动画时序后面

### 8. Content & Microcopy（8 项）

- 按钮文案具体（"Save API Key" 而非 "Continue" / "Submit"）
- 生产环境不出现占位符/lorem ipsum
- 截断已处理（`text-overflow: ellipsis`、`line-clamp` 或 `break-words`）
- 主动语态（"Install the CLI" 而非 "The CLI will be installed"）
- 加载文案以 `…` 结尾（"Saving…" 而非 "Saving..."）
- 破坏性操作有确认弹窗或撤销窗口
- **Happy talk**：欢迎段与自我表扬（"Welcome to..."）。要标出来，并报"本页 X 字，其中 Y（Z%）是 happy talk。"
- 说明超过一句话即意味着设计失败：既标说明，也标它所代偿的那个交互

### 9. AI Slop Detection（黑名单模式 + 检测器规则 + 判断性线索）

判据：**一个受尊敬的工作室里的设计师，会不会把这个发出去？**

**黑名单模式（11 类）**
1. 紫/靛蓝渐变背景，或蓝紫配色
2. **三栏特性网格**（彩色圆圈图标 + 粗标题 + 两行描述，对称重复三次）——最具辨识度的 AI 布局
3. 彩色圆圈图标当区块装饰
4. 所有东西都居中
5. 全局统一大圆角
6. 装饰性光斑、漂浮圆球、波浪 SVG 分隔线
7. emoji 当设计元素
8. 卡片左侧彩色竖条
9. 通用 hero 文案
10. 模板化区块节奏
11. `system-ui` / `-apple-system` 当主字体

**检测器规则名（上游自动扫描；本形态改为人工按形态核对，命中即记该 id）**
`[border-accent-on-rounded]` 圆角卡片上的强调边框 · `[overused-font]` 过度使用的展示字体 · `[flat-type-hierarchy]` 平的字级层次 · `[gradient-text]` 渐变文字 · `[cream-palette]` 奶油色默认调色板 · `[nested-cards]` 卡片套卡片 · `[shape-assembled-illustration]` 用形状拼出的插画 · `[dark-glow]` 深色模式辉光 · `[radial-halo]` 径向光晕 · `[radial-spotlight-glow]` 聚光灯辉光 · `[marquee]` logo 走马灯 · `[icon-tile-stack]` 每个标题上方都压一枚图标块 · `[italic-serif-display]` 斜体衬线展示字体 · `[hero-eyebrow-chip]` hero 眉标胶囊 · `[kicker-above-heading]` 标题上方的 kicker · `[marketing-buzzword]` 营销套话 · `[aphoristic-cadence]` 箴言式节奏 · `[oversized-h1]` 过大的 h1 · `[theater-slop-phrase]` 戏剧腔文案

**判断性线索（无规则名，你就是检测器）**
- 渐变按钮当主 CTA——调色板该有一个纯色扛下主行动
- 通用图库 hero，或用灰色占位块代替——要么展示产品，要么什么都不展示
- 一切都是带阴影的圆角卡片——卡片堆叠不是布局
- 一排头像 + 五星 + 没人说过的证言——要么真名真话，要么删掉
- 模板 hero：标题在左、截图在右、两个按钮——每个生成器第一个伸手够的模板
- "Get Started" 与 "Learn More" 当唯一 CTA——点下去买到的结果要写出来
- hero 下三个大数字配小标签（"10k+ users"、"99.9%"）——那是模板在计数，不是产品
- 一排形状相同的卡片
- **同一元素的扫描命中与判断命中算同一条发现**，不要重复计数

### 10. Performance as Design（6 项）

- LCP < 2.0s（应用类）/ < 1.5s（内容类）
- CLS < 0.1（加载期间无可见布局跳动）
- 骨架屏质量：形状与真实内容布局一致，有微光动效
- 图片：`loading="lazy"`、设了宽高、用 WebP/AVIF
- 字体：`font-display: swap`，CDN 源做了 preconnect
- 无可见字体替换闪烁（FOUT）——关键字体预加载

> 本形态的取证限制：LCP/CLS 精确值不可得。用 `browser_perceive(action="wait", kind="page_ready")` 的就绪时序 + 视觉证据给**粗略体感**，并标注"体感，非指标"。

## Phase 4：交互流程审查

用 `browser_operate(do="click"/"scroll"/"press_key")` 走一遍主流程；每步之后用 `browser_perceive(action="snapshot")` 重新取页面状态（引用会失效，必须重新寻址）。

**注意**：本仓浏览器通道**只读感知 + 有限操作**，没有上游 `aside` 的任意脚本能力。表单在非本地目标上**不要提交**——只填不提交。

评估四点：

- **响应手感**：点下去有反应吗？有延迟或缺失的加载态吗？
- **转场质量**：转场是有意设计的，还是通用/缺失？
- **反馈清晰**：动作明确成功还是失败？反馈是即时的吗？
- **表单打磨**：焦点态可见？校验时机正确？错误信息离来源近？

**叙述模式**：用第一人称叙述流程（"我点 'Sign Up'……3 秒后还在转……"），点名每个元素、它的位置与视觉权重。

### Goodwill Reservoir（跨流程追踪）

维护一个启发式善意存量表，起点 70/100。**重要的是消耗与回填的过程，不是最终数字。**

**消耗**：藏起用户想要的信息（定价、联系、配送）−15；插入页/闪屏/强制导览 −15；格式惩罚（电话号码里拒绝破折号）−10；不必要的信息索取 −10；外观粗糙 −10；每个含混的选择 −5
**回填**：主任务显而易见 +10；有具体修复的优雅错误恢复 +10；提前讲清成本与限制 +5；每个被省下的步骤（直达链接、智能默认值、自动填充）+5；出问题时道歉 +5

以仪表盘形式逐行报告：

```
Goodwill: 70 ████████████████████░░░░░░░░░░
  Step 1: Dashboard   70 → 55  (-15 interstitial tour popup)
  FINAL: 55/100
```

**低于 30 = 关键 UX 债务；30–60 = 需要处理；高于 60 = 健康。**把最大的消耗项与回填项作为发现上报。

## Phase 5：跨页一致性

跨页对比截图与观察：

- 导航栏是否各页一致？
- 页脚是否一致？
- 组件复用 vs 一次性设计（同个按钮在不同页样式不同？）
- 语气一致（一页俏皮、一页 corporate？）

## Phase 6：编译报告

### 评分系统

**双头条评分**：
- **Design Score: {A–F}**——10 个类别的加权平均
- **AI Slop Score: {A–F}**——独立评级 + 一句狠话

**单类别等级**：A 有意且打磨到位；B 扎实，个别不一致；C 能用但泛化、没有观点；D 问题明显，显得粗心；F 实际在伤害用户。

**等级计算**：每类别从 A 起算。每条 **High** 影响发现降一档；每条 **Medium** 影响发现降半档；Polish 级发现记录但不降级。最低 F。

**Design Score 权重表**：

| 类别 | 权重 |
|---|---|
| Visual Hierarchy | 15% |
| Typography | 15% |
| Spacing & Layout | 15% |
| Color & Contrast | 10% |
| Interaction States | 10% |
| Responsive | 10% |
| Content Quality | 10% |
| AI Slop | 5% |
| Motion | 5% |
| Performance Feel | 5% |

AI Slop 占 Design Score 的 5%，同时作为独立头条指标单独评级。

### 基线文件（供回归对比）

上游写 `$REPORT_DIR/design-baseline.json`。本形态改为**可选**落盘到 `reports/design-baseline.json`（`reports/` 是本仓 runtime-output 目录，不进版本库）：

```json
{
  "schemaVersion": 2,
  "date": "YYYY-MM-DD",
  "url": "<target>",
  "designScore": "B",
  "aiSlopScore": "C",
  "categoryGrades": { "hierarchy": "A", "typography": "B" },
  "findings": [
    { "id": "FINDING-001", "title": "...", "impact": "high", "category": "typography",
      "evidence": "<描述或截图路径>", "rule": "[kicker-above-heading]" }
  ]
}
```

`rule` 字段仅在该发现命中某条检测器规则名时填写；本形态为人工判读，**不写"检测器扫描数"这类上游才有的字段**。

### 回归输出

存在上一次基线（或用户要求做回归）时：

- 取最近一份可读的 `reports/design-baseline*.json`；读不到就说"previous baseline unreadable (first scan)"。
- 加载基线等级，逐类别对比 delta，列出新增发现与已解决发现。
- **逐条计数有抖动**（页面是活的），所以计数只作参考，**"某条 id 出现/消失"才是信号**。
- 对比只在规则集合与目标集合一致时才做；不一致就直说"规则集/目标集变了，不做对比"，不要硬凑一个 `+N`。
- 把回归表追加到报告。

## 设计批评格式

把发现写成四种句式之一，并绑定用户目标，每条都给出具体改进：

- **"我注意到……"**（观察）
- **"我想知道……"**（提问）
- **"如果……会怎样？"**（建议）
- **"我认为……因为……"**（有理由的判断）

## Phase 7：分诊

把全部发现按影响排序，然后决定修哪些：

- **High**：先修。影响第一印象与用户信任。
- **Medium**：接着修。削弱精致感，被下意识感知。
- **Polish**：有时间就修。区分"好"与"great"。

**无法从源码修的发现**（第三方控件问题、需要文案团队给的内容）**无论影响级别一律标为 deferred**，并写明交接方式。

## Phase 8：修复循环

按影响顺序处理每条可修发现。

**8a. 定位源码**：用 `search_files`（按类名/组件名/样式文件模式）找到负责该问题的文件。**只改与该发现直接相关的文件**；优先改样式而不是重构组件结构。

**8a.5. 目标描述（可选）**：若发现涉及视觉布局、层级或间距（不是改个颜色值那种小修），先写出"修好之后应该长什么样"的一段描述，并复用提取到的设计系统（同样的颜色、字体、圆角、间距尺度），**不引入新调色板或新字体**。
> 上游此步调用 gstack 自己的 design binary 生成目标 mockup；本形态**没有该二进制**，降级为文字目标描述。需要视觉方向时改用本仓 `frontend-design` 技能给美学方向，需要结构化方案时用 `brainstorm_design`。

**8b. 修复**：做最小必要改动。

**8c. 验证**：重新 `browser_perceive` 取证，确认该发现已消除且**没有引入新问题**（回归：新截图对比改动前后的同一页面）。修复前后的差异要留证。

## 重要规则

1. **像设计师，不像 QA 工程师**：判"感觉对不对、像不像有意图"，不只判"能不能用"。
2. **截图是证据**：每条发现至少要有一处证据；能标注就标注到具体元素。
3. **具体可执行**："把 X 改成 Y，因为 Z"，绝不写"间距感觉不对"。
4. **不读源码**：评估渲染结果，不评估实现。
5. **直说 AI slop**：大多数开发者看不见它。
6. **Quick Wins 很重要**：报告必须含 "Quick Wins" 段——3–5 条影响最大、单条耗时 <30 分钟的修复。
7. **棘手 UI**：当快照树漏掉看得见的控件（可点的 div、canvas 按钮）时，改用视觉证据定位，并用 `browser_operate` 按可见文字寻址。
8. **增量记录**：发现一条记一条，不要攒到最后一次性写。
9. **深度优于广度**：5–10 条有充分证据的发现，胜过 20 条含糊的。
10. **把证据交给用户**：截图等证据文件路径要在报告里写清楚，让用户能直接打开查看。

## 与本仓其它技能的分工

- 代码正确性/安全性 → `code_review`
- 文档级多角色设计审查 → `design_review`
- 追问式设计评审（把边界逼出来）→ `grill_me`
- 新建界面的美学方向（不是审计既有界面）→ `frontend-design`
- 方案发散与选型 → `brainstorm_design`
