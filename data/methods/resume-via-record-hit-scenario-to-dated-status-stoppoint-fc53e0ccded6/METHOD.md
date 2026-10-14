---
method_id: resume-via-record-hit-scenario-to-dated-status-stoppoint-fc53e0ccded6
name: resume-via-record-hit-scenario-to-dated-status-stoppoint
description: 极简续跑指令（如'继续'）且无活动 goal 时，若首轮 record 检索已命中一张 scenario 与续跑语境同形的卡（点名跨会话 Goal、平台/工件专名、未完成任务），该命中本身就是续跑锚：提取其独有字面做一次内容搜索定位工作区目录，按日期读最新 STATUS/ledger 重建停点，再从停点导出后续动作。关键补充：此类内容/发布工作常未入 git（untracked），miss 回执的最近文档引导与 git log 均不指向它——本集沿用旧卡（miss 回执+git delta）三条边全部落空，实际靠命中卡字面+内容搜索才落到 promotion/ 工作区。与 resume-continuation-via-named-provenance-and-git-delta 互补而非重复：那条的真值账是 git delta，本条覆盖 git 看不见的内容线。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:43966c4f-fe71-4779-a054-72a945697fa7:205:16c5bb1277753a67a9a7
evidence_refs: learning:learn:63591ce5db30
created_at: 2026-10-13T22:48:06.752175+08:00
updated_at: 2026-10-13T22:48:06.752175+08:00
---
## Trigger
用户仅给极简续跑指令（如'继续'）且工具回报无活动 goal；同时 record/experience 库检索已命中一张卡，其 scenario 显式描述'跨会话继续某 Goal、存在未完成子任务'并与当前续跑语境同形

## Discriminator
命中卡 scenario 是否点名与续跑目标同域的独有字面（平台名/工件名/未完成任务描述）。且目标工作多为未跟踪内容文件：miss 回执的最近文档引导不含它、git log/status 只见 '??' 条目——证明 git delta 与 miss 回执这两条旧 provenance 边在此类任务上是干涸的，唯一有效索引是 record 命中卡与文件内容搜索

## Short path
- 未知量=继续什么：直接读已命中的那张卡（不换词重搜），确认 scenario 与续跑语境同形，提取独有字面（如平台名'今日头条/知乎专栏'）
- 未知量=工作区在哪：用这些独有字面做一次文件内容搜索，命中 promotion/ 等工作目录的 PLAN/STATUS/receipts 文件
- 未知量=停在哪一步：ls 该目录按日期/mtime 排序，读最新 STATUS-*.md 与 PLAN ledger，得到停点（已发哪些、待发哪些、遗留 draft 在哪）
- 从停点导出下一步：审稿→发布→公网回读验收→写回执并更新 STATUS；不再回到换措辞检索、全库枚举或 git log 找内容线状态

## Stop conditions
- 最新 STATUS/ledger 已给出明确停点，且所有续跑动作均由停点导出
- 发布类续跑以公网 URL 回读验收通过并落回执为终点（不以编辑器内状态收尾）
- 若命中卡 scenario 与续跑目标不同域，立即放弃该锚，回到通用续跑路线

## Verification
- 读到的 STATUS 文件日期不早于上一会话实际停点；其引用的 receipts/ledger 路径真实存在
- 续跑产出回写新 STATUS/回执后，仅凭该文件可完整重建本次决策链
- 全程对同一检索库无同义换词的重复查询（本集可观察重复调用 6 次）

## Counterexamples
- 命中卡只是历史教训且 scenario 与当前续跑目标不同域（如本集同时命中的 pymupdf OCR 核对卡）——不能当锚
- 工作全部在 git 跟踪内且 record 无同形命中——此时旧卡（miss 回执文档引导+git cherry/diff delta）仍是正确路线，不应绕道内容搜索
- STATUS 晚于实际停点未更新（上一会话只留下未登记的 draft，如本集 articles/ 下的新稿）——需叠加 mtime 最新的 draft 文件确认停点，不能只信 STATUS
