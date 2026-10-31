# NOTICE — gstack-plan-design-review

## 上游

- 项目：garrytan/gstack（https://github.com/garrytan/gstack）
- 固定版本：`088bfc5914f8001a3d49b3a0c35d6f7cb800268c`（2026-10-31）
- 源目录：`plan-design-review/`（`SKILL.md`、`sections/review-sections.md`、`sections/preamble.md`、`sections/checklist.md`）
- 许可：MIT，Copyright (c) 2026 Garry Tan（上游 LICENSE 随附）

## 本地改动（逐条）

1. **frontmatter**：`name` 改为 `gstack-plan-design-review`；`description` 改写为中文并补触发词；上游英文原描述保留在 `metadata.upstream-description`；新增 `license: MIT`、`metadata.vendored-from`、`metadata.adapted-for`。
2. **`AskUserQuestion` 移除**：上游用该工具提问并硬停；本仓无此工具，改为**在回复正文列出选项（字母+括号起头）并停下等待**。硬停语义保留。
3. **Scope gate 保留**：两个例外（计划模式自动选 B、用户明确指名目标）与"存疑就问"的默认规则逐条保留。
4. **design binary 降级**：上游 Step 0.5 在 `DESIGN_READY` 时不问就生成 mockup 图像；本形态无图像生成通道，改为**文字目标描述**并显式声明降级，指向上游未涉及的本仓 `frontend-design` / `brainstorm_design`。
5. **独立外部声音改道**：上游调用独立提案通道；本形态改用本仓 `design_review` 工具或 `spawn_subagent`，**保持"不把草稿透露给独立声音"的纪律**。
6. **`DESIGN.md` 格式检查人工化**：上游用 `gstack-design-md.ts check/convert` 判定 spec/legacy 并做转换；本形态改为人工检查 front matter token、小节结构与遗留标记，无法判定时**保持原样并说明**，不擅自转换。
7. **Retrospective Check 改道**：上游检索上游状态目录中的历史；本形态改用 `search_records(kind="experience"|"lesson")` 与项目既有文档。
8. **产出结构保留**："NOT in scope" 段、"What already exists" 段、实施任务（Markdown + JSONL）、完成摘要、未决决策、已批准目标、评审报告写回计划文件、评审日志、评审就绪仪表盘 —— 全部保留；上游用 `jq` 逐条写任务记录，本形态改为直接写文件（同一产出结构）。
9. **方法论逐条保留**：设计哲学（不改代码、DESIGN.md 是建议不是批准、缺口须逐条批准）、9 条设计原则、Krug 行为学段落（扫读/满意化/trunk test/寻路/移动端赌注/善意存量）、优先级层级、PRE-REVIEW SYSTEM AUDIT（回顾检查 + UI 范围检测）、Step 0 的 0A–0D（含 0D 的 STOP）、**上游 7 个 Pass 逐条保留**（1 Information Architecture / 2 Interaction State Coverage / 3 User Journey & Emotional Arc / 4 AI Slop Risk / 5 Design System Alignment / 6 Responsive & Accessibility / 7 Unresolved Design Decisions）、0–10 评分法与迭代循环（"输入计划里已列出的缺口仍是未解决发现"等纪律）、Exit Plan Mode 阻塞门。

## 诚实边界

这是**流程方法**的本地化移植，不含上游脚本运行时。上游依赖的 `AskUserQuestion` / design binary / `gstack-design-md.ts` / 上游状态目录 / `jq` 任务流水线**在本形态下全部不可用**。移植的是评审流程与维度，不是上游的自动化能力；图像 mockup 能力缺失会使"视觉目标"这一步强度下降。
