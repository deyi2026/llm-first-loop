---
method_id: completed-goal-followup-via-goal-artifact-index-and-commit-ledger-710964863eab
name: completed-goal-followup-via-goal-artifact-index-and-commit-ledger
description: 后续任务作用于一段已完成、由 goal 记录跟踪的工作（评测/预注册流水线/已交付工件集）时，“产出了什么、结论如何、工件在哪”已被两条点名 provenance 源预先收窄：goal 记录枚举的确切工件名，以及完成 commit 的 message（常直接携带裁决级事实与下游工件指向，如 forensic）。先沿这两条边定向定位并读取 RESULT/notes/forensic，再产出交付物；docs 全量 find、evidence 库翻页、换措辞 search 只在这条边断掉后才允许。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:abda90a9-c633-4664-b777-2ef993c8f7d9:649:1c308e6cb7880f6316d7
evidence_refs: learning:learn:07be90ed3795
created_at: 2026-10-06T02:01:13.023893+08:00
updated_at: 2026-10-06T02:01:13.023893+08:00
---
## Trigger
用户对已完成的 goal 跟踪工作提出衍生请求（审批转化、经验沉淀、失败子集处置、启用登记），当前未知量是产出物、结论与工件位置；get_goal/status 已返回 complete 并点名确切文件名

## Discriminator
宽发现启动前已存在：goal 记录（complete）已枚举交付工件确切名（PREREG/build/analyze/盲表）——单这一条即把“docs 全量 find + evidence 翻页 + search_docs”缩成“按名字词干定向定位 + 看该路径 git log”；定位后 commit message 随即携带裁决级事实（“一次性裁决 PASS κ=1.0 0/40 分歧”“L-dominant 6/6 label-noise”+ forensic 指向），此后任何换措辞检索都无信息增量

## Short path
- 读 goal 记录：未知量=这项工作由哪些工件构成 → 得到确切文件名清单与 goal id
- 按名字词干定向定位（find -name 'IQ-*' / 'iq_*'）+ 查看该路径 git log：未知量=工件在哪、裁决是什么 → commit message 直接给出结论与下游指向
- 读同目录 RESULT 文件：未知量=门槛级事实（gates、认证数），支撑启用/激活项
- 读登记的 deviation/notes 文件：未知量=需如实披露的偏离，支撑经验沉淀项
- 失败子集处置：沿 commit 点名的 forensic 工件读失败分层与 case 清单，与未认证例做 subject 级一一对应：未知量=已知噪声底还是新模式
- 每项所需事实都有已读工件背书即停止发现，再产出登记/用户操作包/lesson

## Stop conditions
- 用户请求的每一项都有已读工件（RESULT/notes/FORENSIC/registry）背书，发现阶段结束
- 失败子集与既有 forensic 分层完成一一对应并登记（或确认清单外新模式，转开新 forensic 而非继承）
- goal 记录点名的工件全部定位读取完毕，宽发现始终未启动

## Verification
- 终稿每条结论可指向本会话实际读过的文件路径；计数（未认证例数、分母）由数据推导并与文件一致，不硬编码
- 定位到的目录与 goal 记录枚举的工件名一致；引用 commit message 的裁决事实前与 RESULT 正文交叉核对一致

## Counterexamples
- goal 记录缺失，或其点名工件在工作区不存在/mtime 晚于最后 commit（记录可能过期）→ 先做新鲜度核对，再决定是否需要宽发现
- 后续问题本身就是 docs/ 的内容（历史校准、eval 报告检索）→ find docs 在路径上，不适用本卡
- commit message 为泛化文本（'wip'/'update'）不含裁决事实 → 不能当账本，须直接开读工件
- 对存在并发写者的共享资源要做终局/收官断言 → 应走 fresh-read 权威记录方法，本卡不覆盖
