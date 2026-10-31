# NOTICE — gstack-design-review

## 上游

- 项目：garrytan/gstack（https://github.com/garrytan/gstack）
- 固定版本：`088bfc5914f8001a3d49b3a0c35d6f7cb800268c`（2026-10-31）
- 源目录：`design-review/`（`SKILL.md`、`SKILL.md.tmpl`、`sections/`）
- 许可：MIT，Copyright (c) 2026 Garry Tan（上游 LICENSE 随附）

## 本地改动（逐条）

1. **frontmatter**：`name` 改为 `gstack-design-review`；`description` 改写为中文并补触发词；上游英文原描述保留在 `metadata.upstream-description`；新增 `license: MIT`、`metadata.vendored-from`、`metadata.adapted-for`。
2. **浏览器通道重写**：上游全部依赖 `aside repl` 浏览器脚本与 `pg.screenshot` / `pg.evaluate`；改为本仓 `browser_perceive`（含 `vision="evidence"`）、`browser_operate`、`read_image`。
3. **设计系统提取降级**：上游用 `pg.evaluate` 直接读 `getComputedStyle` 取字体/颜色/字号/触控目标；本仓无任意 JS 求值，改为"目测 + 标注未能取证"，并明确列出哪些指标**不可得**（精确字号、字重、间距、触控尺寸、LCP/CLS 数值）。
4. **检测器降级**：上游有 21 条自动 detector 规则（`gstack-design-detect.ts`）与置信度统计；本形态改为**人工按形态核对**，保留全部 21 个规则名与命中形态，不保留"扫描计数"类字段。
5. **状态目录移除**：上游用 `$GSTACK_STATE_ROOT` 存 `design-baseline.json`；改为可选写入 `reports/design-baseline.json`（runtime-output 目录，不进版本库）。
6. **基线 schema 调整**：保留 `schemaVersion/date/url/designScore/aiSlopScore/categoryGrades/findings`，删除上游才有的 `detector` 块（本形态没有自动扫描器，写它就是造假），改为在 finding 上加 `evidence` 与 `rule` 字段。
7. **目标 mockup 降级**：上游 Step 8a.5 用 design binary 生成目标图；改为文字目标描述，并指向本仓 `frontend-design` / `brainstorm_design`。
8. **规则第 10 条改写**：上游要求把截图复制到用户可见目录并用 Read 工具展示；改为在报告中写清证据文件路径（`read_image` 已在会话内消费视觉证据）。
9. **方法论逐条保留**：模式分类器（Persuade/Operate/Read/Experience/Hybrid）、14 条硬拒绝标准、Trunk Test（6 问 + PASS/PARTIAL/FAIL 阈值）、10 类审计清单（含全部条目与项数）、Goodwill Reservoir（消耗/回填数值与阈值）、评分体系（10 类别权重表 + 字母等级计算规则）、回归对比纪律、批判句式（"我注意到/我想知道/如果…/我认为…因为…"）、重要规则 10 条 —— **均按上游原文保留**，只改工具与状态引用。

## 诚实边界

这是**流程方法**的本地化移植，不含上游脚本运行时。上游依赖的 `aside` / headless browser / design binary / `gstack-design-detect.ts` / `$GSTACK_STATE_ROOT` **在本形态下全部不可用**；相关环节已按上文逐条降级，其中自动检测器改为人工判读，**判读强度低于上游自动扫描**。移植的是评审方法与清单，不是上游的自动化能力。
