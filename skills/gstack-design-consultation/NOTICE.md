# NOTICE — gstack-design-consultation

## 上游

- 项目：garrytan/gstack（https://github.com/garrytan/gstack）
- 固定版本：`088bfc5914f8001a3d49b3a0c35d6f7cb800268c`（2026-10-31）
- 源目录：`design-consultation/`（`SKILL.md`、`sections/proposal-and-preview.md`、`sections/preamble.md`）
- 许可：MIT，Copyright (c) 2026 Garry Tan（随附于本目录 `LICENSE`，逐字取自上游 LICENSE）

## 本地改动（逐条）

1. **frontmatter**：`name` 改为 `gstack-design-consultation`；`description` 改写为中文并补触发词；上游英文原描述保留在 `metadata.upstream-description`；新增 `license: MIT`、`metadata.vendored-from`、`metadata.adapted-for`。
2. **`AskUserQuestion` 移除**：改为在回复正文直接提问并停下（硬停语义保留）。
3. **视觉研究通道替换**：上游用 headless 浏览器（`$B`/`aside`）做视觉研究；改为 `browser_perceive(vision="evidence")` + `read_image`，案头研究用 `web_search` / `web_fetch`。
4. **不可用时的诚实处理**：上游区分 `NEEDS_SETUP`（不构建、不提供构建，明确告知不可用）与一般不可用；本形态保留同一纪律，并明确"不用单元测试或 curl 冒充视觉研究"、"不把记忆中的模式当成观察到的发现"。
5. **taste profile 改道**：上游读 `$GSTACK_STATE_ROOT/projects/<slug>/taste-profile.json`（含四维度 approved/rejected、置信度按闲置每周衰减 5%、保留 session 上限 50）；本形态从 `search_records` 与项目文档读取，**不做衰减计算**，且必须标注样本量、不得编造。
6. **design binary 降级**：上游 Path A 生成 AI mockup 图像；本形态改为文字目标描述 + 以用户既有界面（`browser_perceive`）作"现状 vs 目标"对照，并显式声明降级。
7. **Path B 保留并本地化**：上游 Path B 是 HTML 预览页回退；本形态保留该结构，产出到 `reports/design-preview.html`（runtime-output 目录），并补"写完自检渲染"步骤。
8. **`DESIGN.md` 格式检查人工化**：上游用 `gstack-design-md.ts check/convert/mark` 判定并转换格式；本形态改为人工检查（front matter 扁平 token、小节结构、遗留标记），无法判定时保持原样并说明。
9. **Capture Learnings 改道**：上游写回上游状态目录；本形态改为 `search_records` / `save_experience` 或项目内设计文档。
10. **方法论逐条保留**：Phase 0 预检（`DESIGN.md` / `design-system.md` 判定与 update/fresh/cancel 三分支）、Phase 1 产品上下文（"让人记住的一件事"作为锚点、品味是偏好不是约束、冲突要显式标记）、产品简报（**同一份简报给草稿与两条独立声音，且不透露自己的方向**）、Phase 2 研究（先问再做、两步研究、来源 URL、不可用的诚实措辞）、Phase 3 完整提案（设计知识库、一致性校验、独立提案后综合、分歧要给理由）、Phase 4 下钻调整（只改被点到的部分并重跑一致性校验）、Phase 5 比较板与反馈循环、Phase 6 写 `DESIGN.md` 并确认（**spec 模板小节逐节保留**：Overview / Colors / Typography / Layout / Elevation & Depth / Shapes / Components / Do's and Don'ts / Motion / Decisions Log / Design System）、重要规则 7 条。

## 诚实边界

这是**流程方法**的本地化移植，不含上游脚本运行时。上游依赖的 `AskUserQuestion` / headless 浏览器 / design binary / `gstack-design-md.ts` / 上游状态目录与 taste profile 衰减算法**在本形态下全部不可用**。移植的是共建设计系统的流程与 `DESIGN.md` 模板，不是上游的自动化能力；图像 mockup 与置信度衰减两处强度下降，已在正文逐处标注。
