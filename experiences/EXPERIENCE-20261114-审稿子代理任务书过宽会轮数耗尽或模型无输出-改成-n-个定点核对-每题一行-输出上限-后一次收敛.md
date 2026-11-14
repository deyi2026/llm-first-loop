---
title: 审稿子代理任务书过宽会轮数耗尽或模型无输出；改成「N 个定点核对 + 每题一行 + 输出上限」后一次收敛
scenario: "d84 的 R2 窄复审（送 diff + 事实清单 + 5 条审阅清单，只收 P0/P1/P2a）因子代理达到轮数上限未收敛（truncation_detail=exhausted_without_verdict，tools=20, tokens_out=26930），按规则不能当结论用；改派 R3（只收 P0/P1 + 5 条清单）时子代理模型直接未生成有效文本（child_outcome=failed，finish_reason=stop）。第三次改派把任务书压到「5 个定点核对题 + 每题一行 + 输出不超过 14 行 + 只读」，4 轮内即返回 VERDICT: PASS / P0=0 P1=0。"
root_cause: ""
solution: 审稿子代理的任务书要写成「可机械判定的定点问题」，而不是「按清单全面审查」：逐条列出要核对的文件与行号、限定答案格式（每题一行）、给出输出行数上限（≤14 行）、并显式声明只读/禁联网/禁 git。宽任务书 + 大输入包会让子代理在工具调用上耗尽轮次，或触发模型输出预算耗尽。当前性验证：复现——把任务书改成 5 问形式后 spawn，应在 ≤6 轮内返回带 VERDICT 的结论文本；对照同一次发布链路里的三个子代理 child_id：subagent_8f8d6f4f71eb（R1 全量审，正常收敛）、subagent_c4d4e39f222e（R2 宽窄审，耗尽）、subagent_7985abe62f47（R3 失败）、subagent_811777917830（5 问定点审，PASS）。
evidence: "子代理回执：subagent_c4d4e39f222e（child_state=truncated, exhausted_without_verdict）、subagent_7985abe62f47（child_state=failed, finish_reason=stop, tokens_out=192）、subagent_811777917830（child_state=completed, rounds=4, VERDICT: PASS P0=0 P1=0）；审稿包 docs/promotion/receipts/d84-review-pkg-R3.md（18,649 字符）"
tags: [subagent, review, task-narrowing, promotion]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-14T08:32:13.582420+08:00"
updated_at: "2026-11-14T08:32:13.582420+08:00"
supersedes: [EXPERIENCE-20261113-审稿子代理回执仍可能被截断-根因是子代理自行检索超预算-不是排版-缺失项不猜-另开独立子代理全量复审, EXPERIENCE-20261104-审稿子代理在本工作区跑仓库级命令会-60s-超时-改用静态读数回执离线核对并令回执走最终回复正文, EXPERIENCE-20261106-审稿子代理必须给-读取次数与对象-的硬约束-只说-只读该包-会因反复-read-file-失败重试把]
---