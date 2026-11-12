---
title: 共享仓库定期入库：按资产范围限定暂存，禁用 git add -A
scenario: llm-first-loop-mirror 主工作区被多个并发会话共用（含活跃 lane/推广会话），定期知识资产入库任务若按原文执行 git add -A，会把他人未提交的在途源码/测试一并夹带进知识入库提交。
root_cause: ""
solution: 入库时先 git status 分清归属：只暂存 data/methods/、experiences/ 与已完成的 docs/ 审计文档与治理回执；src/ scripts/ tests/ 与当日在改的设计文档一律不暂存（并发会话会在其自己的流程里收口）。提交前跑 bash scripts/git_security_scan.sh --staged；命中 /Users/<用户名>/ 类路径时按仓库既有惯例改写为 ~/Project/<repo> 再提交；入库回执写入 docs/governance/receipts/knowledge-flush-weekly-<sched>-<date>-r<N>.json 记录 sha、脱敏动作与排除清单。
evidence: sched-50432bfc 第 4 次执行（2026-11-12）：入库提交 719755836（31 文件/2528 行，9 张方法卡 + 7 条经验卡 + 15 份文档），回执提交 c5a31ac1b；4 份 merge-review 回执含本机绝对路径，按 ~/Project/llm-first-loop-mirror 改写后 git_security_scan.sh --staged 通过（exit 0）；并发会话 ea89d59c… 在执行期间仍在改 scripts/restore_prebackup.sh，未被夹带。
tags: [git, knowledge-flush, 并发会话, 安全扫描, 入库]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-12T20:56:03.894096+08:00"
updated_at: "2026-11-12T20:56:03.894096+08:00"
supersedes: [EXPERIENCE-20261028-共享-mirror-仓库的全量测试-归因与提交纪律-job-id-免疫-陈旧锁-文件交换归因-显式路]
---