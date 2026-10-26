---
title: 全量 ci_gate 会把 reports/*.json 时间戳副作用刷进工作树 diff，导致 review_admission 192KB 审查包超限
scenario: RULE-AI-28 全量门禁 + review_admission 交替执行的安装内：跑完 bash scripts/ci_gate.sh 后立刻申请新一轮 review_admission(kind=full_test)。
root_cause: ""
solution: review_admission 被拒 review_artifact_exceeds_192kb 时，先查 git diff 是否被测试套件副作用撑大（本仓库主要是 reports/phase*/*.json 被全量套件重写时间戳），git checkout -- reports/ 还原后重试；不要试图通过缩小 artifact_paths 清单绕过（包按工作树 diff 计算，与清单无关）。
evidence: "evidence://v1/7e70f5cb52f8a72a5dbeb972d644738421852b7527575944f130a6171507f14b（durability 基线提交时刻工作树状态）；2026-10-21 实测序列：r1/r2 准入过→全量跑→r3 两次拒 review_artifact_exceeds_192kb（job-68019c02782d492aa10f 输出含 9951 passed 与 reports 重写）→ git checkout -- reports/（323KB→25KB）→ r3 第三次 accepted=true, candidate_sha256=aa318e94…→全量 exit=0"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-21T07:56:55.644169+08:00"
updated_at: "2026-10-21T07:56:55.644169+08:00"
---

现象：ci_gate.sh 全量跑完，phase 套件会重写 reports/phase*/*.json 的时间戳/墙钟字段（~323KB diff，内容仅数值漂移）。随后 review_admission(start) 以 review_artifact_exceeds_192kb 拒绝，且无论 artifact_paths 传 10 个文件还是单个 42KB 文件都同样被拒——说明审查包按整个工作树 diff 计算，与清单无关。处理：git checkout -- reports/ 还原副作用后 diff 回到 ~25KB，准入立即通过。预防：两轮全量/准入交替时（守卫基线更新后再准入很常见），在 review_admission 前先还原 reports/；同理任何"跑完套件→马上提准入"的流程都应先清测试写入的工作树副作用。