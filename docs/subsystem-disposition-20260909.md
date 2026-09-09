# 子系统处置表（治理北极星落地版）

日期：2026-09-09 ｜ 数据口径：本仓库 src/llm_loop 实测（当日 cloc 口径，非历史快照）

## 0. 北极星判据

程序供证据、供工具、供回路，决策留给模型。每个子系统只问一句：
**它在放大模型的智力，还是在替模型做决定？**

- 放大 = 看得更全（证据/记忆）、记得更久（经验/方法）、动得更快（工具/子代理）、知错能改（反馈/评估）→ 保留加强
- 替代 = 硬门禁、启发式裁决、静默截断、兼容包袱 → 收缩，且每处门禁必须有「模型可举证否决」出口

**所有者收正（2026-09-09）**：软件 AI 的工具与辅助、规则与经验、方法掌握、**学习积累才是中心**。
凡不利于大模型智力与执行力发挥的——过时机制、冲突约束、替模型做决定的机械——一律摒弃。
据此北极星判据升维为两层：
1. 放大 or 替代（如上，管存量）；
2. **积累 or 负担（管增量）**：新改动若增强 学习回路（memory/experiences/skills/methods 的检索质量与沉淀路径）默认放行；
   若增加控制机械（新校验/新流程/新兼容层），必须回答「为什么模型+现有工具自己做不到」，否则不做。

## 1. 全量数据（实测）

总 88,946 行 / 21 个子包 + 顶层 3,774 行。数据目录 data/ 2.1G（运行时产物，不入库）。
deprecated/legacy/compat 标记：src/llm_loop 范围内 70 个文件命中。

结构性倒挂（核心洞察）：
- 控制机械（core + introspection + tools + task_quality + cache_guard）≈ 49,280 行，占 55%
- 智力放大器（memory + experiences + skills + methods + cognitive + subagent + feedback + eval）≈ 12,582 行，占 14%
- **该大的不大，不该大的最大。** core 内部 runtime 骨架六件套（history 2237 / session 1683 / episode_history 1567 / engine 1546 / events 1285 / build 1178）≈ 9.4K 行，是单点最大的器官。

## 2. 处置表

| 子系统 | 行数 | 处置 | 依据与第一步动作 |
|---|---|---|---|
| memory | 5,750 | 保留加强 | 检索质量是放大器地基；第一步：定义「检索命中率」度量，让加法有裁判 |
| experiences | 708 | 保留加强 | 体量与价值倒挂；第一步：与 methods 打通沉淀路径 |
| skills | 108 | 保留加强 | 同上；外部技能装载面 |
| methods | 588 | 保留加强 | v1 刚落地（Mixin→Service 组合化）；观察 30 天使用数据再扩 |
| cognitive | 1,565 | 保留加强 | 新增；与 feedback/eval 职责边界写清，防再次重叠 |
| subagent | 1,785 | 保留加强 | 隔离执行是关键能动性 |
| feedback | 1,125 | 保留加强 | 知错能改的回路 |
| eval | 941 | 保留加强 | 同上；与 introspection 的重叠部分划归 eval |
| core | 24,267 | 收缩 | 目标 <15K：engine/build 逐步抽纯函数到可测模块；history/session/episode_history 三史合一提案 |
| introspection | 11,877 | 收缩 | 与 event_log/eval/feedback 职责重叠；第一步：出职责矩阵，重复能力只留一个权威侧 |
| tools | 10,164 | 收缩 | 每个硬校验/静默截断登记成表，逐个补「模型可举证否决」出口 |
| task_quality | 2,194 | 收缩 | 启发式裁决重灾区；改为评估器（供证据）而非门禁（做决定） |
| cache_guard | 778 | 收缩 | 同上原则 |
| feishu | 5,311 | 观察 | 出站通道，按白名单运行即可，不加功能 |
| web | 4,841 | 观察 | 同上 |
| event_log | 3,528 | 观察 | 审计职责保留；与 introspection 去重后定位 |
| llm | 3,472 | 观察 | provider 层稳定 |
| workspace | 2,143 | 观察 | — |
| codearts | 1,999 | 观察 | — |
| runtime | 1,463 | 观察 | — |
| recovery | 565 | 观察 | — |
| 顶层散文件 | 3,774 | 收缩 | 归入子包，顶层只留 __init__/入口 |

## 3. 文件级退役清单（污染清理）

| 对象 | 状态（2026-09-09） |
|---|---|
| .backup/（含 pollution-20260828） | 已从 staged 剔除；.gitignore 已加 `.backup/` |
| swe-*.json | 磁盘已无；.gitignore 已加 `swe-*.json` 防复发 |
| Nexitally_Surge*.conf | 个人代理配置；.gitignore 已加 |
| data/（2.1G 运行时数据） | 历史已 ignore；唯一被跟踪资产 data/calib/h1c_control_bank.json 保留（校准资产） |
| data/runtime/toolmode-off-*/src 快照树 | 磁盘删除待批（涉及不可恢复 rm，列入待用户确认项） |

## 4. 防复发机制（三条）

1. **准入不对称**：放大能动性的改动默认放行；做减法（新增硬门禁/静默截断/兼容层）必须写明「为什么模型自己判断不了」+ 留否决出口。建议进 AGENTS.md。
2. **测试分层**：契约测试（少而稳，钉行为边界）与实现测试（可随重构丢弃）。禁止用实现测试劫持演进——预存在红清单就是当前的现实约束（origin/main 基线 8 项，见 /tmp/lfl-main-baseline-reds.txt，待迁入 docs 归档）。
3. **弃用生命周期**：标记 → 给出下线日期 → 删除。src 内 70 个标记文件按此排队清偿。

## 5. 今日已执行与待办

已执行：
- 污染 unstage（staged 21→18）、.gitignore 三条防复发规则、本处置表落盘。
- **全量重跑判定完成（2026-09-09 17:31）**：七片并行回归（job-29319c4963d84f62bc6a，exit 仅 saf=1）+ r4 全量复核（job-766f63f4fae748809848，/tmp/full_verify_r4.log），两口径一致：**4816 passed / 4 failed / 23 skipped**。
- **与 origin/main 基线 8 项预存红比对完成**：7 项仍存在且全部转绿（定向重跑 exit=0）；1 项（err1210 `test_interleaved_a1_to_a6`）测试已在本线退役，宿主文件现役 2 测试全绿。**基线红残留 = 0**。
- **增量2 判定：通过**。变更面：cognitive/ 4 新模块 + ab_shadow_pilot + injection_span + cr_r1 系列 6 测试等新增，config/history/build/tool_cycle/tool_exec/tail_assembly/honesty 修改。无新增红；净修复 2 项（compact_observability）。当前 4 项 failed 全部为 HEAD 预存红（tests/unit/test_tool_working_set_projection.py，9/7 落盘于本地线，实现 episode_history.py 未被增量2 触碰），且该文件不在 origin/main。

待办：
- ~~全量重跑判定 → 与基线 8 项比对 → 决定 commit/push~~（重跑与比对已完成，见上）。
- **commit 可执行**：增量2 + 本处置表 + 未跟踪三文件（docs/subsystem-disposition-20260909.md、src/llm_loop/core/loop/injection_span.py、tests/unit/test_progressive_fold_retired.py）一并入档。
- **push 待用户确认**：fix/restart-useful-continuity 与 origin/main 已分叉（两边各自落地 method-learning v1），需先定整合策略（merge origin/main / rebase / 直接推分支）。
- 基线清单已迁入 docs 归档：`docs/known-reds-20260909.md`（含"7 绿 1 退役"复核结论）；4 项 working_set HEAD 预存红已登记进同一清单（修复或显式接受二选一，待定）。
- AGENTS.md 准入不对称条款已落地（Admission asymmetry 一节）；快照树 rm 待用户确认。
