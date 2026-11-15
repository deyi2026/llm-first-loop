---
title: 分段过闸推送前先做 DAG 瓶颈边分析：单 commit 增量超闸预算=结构性死锁；首段端点选择会锁路线
scenario: "授权的分段推送任务（llm-first-loop-mirror gitee 同步，93d0098→9a8b3fb，领先 133+ commit）要求按 RULE-AI-28 git_push 闸分段推送，段材料须 ≤360,000 chars（est≤3600s）。"
root_cause: ""
solution: "先在 DAG 上算瓶颈（min over ancestry paths of max edge material），发现 X-crossing 最小边=407,365 chars>上限且 git_push 无 paths 通道→结构性死锁；实测探测（pre-flight 拒绝免费且带归因）确认后停止，推完可行首段（db6a2546a，PASS+推送+ls-remote 验证），提交 EVO-20261115-34ae7c99（多批联合覆盖协议/人工 oversize 通道）并如实上报。"
evidence: "review_admission 拒绝回执（est=4073.7s>3600s, task=407365chars，含 split_plan paths 指引）；同命令+paths 复测回执 review_scope_not_applicable_for_git_push；边权实测 db6a2546a→e1355ccff=573534B、6b652f445→e1355ccff=592998B、6b652f445→06a5ce649=667389B；源码 _resolve_scope git_push+paths 拒绝与 _REVIEWER_MAX_ESTIMATED_S=3600 前置拒绝；e1355ccff parents=6b652f445+7f8c320d3（is-ancestor 实测）；SEG-A 推送成功且 ls-remote 验证 db6a2546a9d61a35c8497420413445aee6bc90e6"
tags: [git-push, rule28, segmented-push, bottleneck-analysis, gate-design-gap, fail-closed]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-15T16:25:41.159121+08:00"
updated_at: "2026-11-15T16:25:41.159121+08:00"
---

分段过审推送前必须先做 DAG 瓶颈边分析：(1) 用 ls-remote 定真远端头，枚举 base..target 的祖先链；(2) 对每条候选边测材料口径大小（git diff base..end 的字符数，审查材料≈diff 全文）；(3) 若存在单 commit 增量 > 闸预算上限（本例 06a5ce649=407,365 chars > 360,000 chars / est 3600s 硬上限），则任何分法都无解——单 commit 是原子单元，push 闸不接受 paths 收窄（review_scope_not_applicable_for_git_push），ref 指针只能落在 commit 上。此时应立即停止分段尝试，fail-closed 上报并提演进建议，不要烧审查轮。
第二个教训：分叉历史（A 枝/B 枝后 merge）里，推第一段的端点选择会把远端锁进该侧——推 A 枝尖（6b652f445）后再无 ≤上限边可达（592,998B），只有 B 侧（db6a2546a→06a5ce649→e1355ccff=185,706B）保持最小瓶颈。选择路线前先算两侧全部穿越边。
第三：材料字符/字节比随内容类型漂移（中文卡 0.77，混合 0.944，纯 ASCII 代码≈1.0）；估算不足为凭，闸的 pre-flight 拒绝免费且带精确归因（task=N chars），用它做终裁。