---
title: 定时续跑裁决全量失败：identity guard 环境固有对照 P0 基线 + ratchet baseline 迁移同步 + 唤醒前已完成提交的核对法
scenario: 定时续跑检查 p1b worktree 全量 pytest（2 failed）并与 P0 基线对照裁决；唤醒时发现前一轮触发已自行完成修复+提交（定时器重叠）
root_cause: ""
solution: 按失败类型分流：runtime identity/env gate 类失败先读 traceback 中的 cwd_match/PYTHONPATH 细节并与 P0 基线 job 同款失败对照定性环境固有；静态 ratchet 类失败先单跑（单跑绿+全量败→查运行期写 src 副作用；两者皆败→baseline 未同步，按治理门显式更新签名再复跑）。唤醒后第一步查 git reflog/log 提交时间 vs schedule 注册时间，确认任务是否已被前一触发轮次完成，再用 event_stream 该时间窗 llm_decide 复原动作链，最后提交后全量重跑终验。
evidence: "job_output job-f012a6577c5844c098de（2 failed）；job-fc109e52aa5141abbb15（P0 基线 1 failed identity 同款）；单跑 evidence://v1/6d32bb21d1aed8ebdbda7e555a8cc63c8d97c56a911d44dbd61d2294224928e7（ratchet 单跑通过+identity PYTHONPATH 细节）；git show HEAD baseline diff（签名 1→1 迁移）；job-4dc151432fa6433da7f8 提交后全量 1 failed/6894 passed"
tags: [pytest, worktree, baseline-ratchet, p0-baseline-compare, scheduled-wakeup, job_output]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-09T10:44:01.188888+08:00"
updated_at: "2026-10-09T10:44:01.188888+08:00"
---

p1b 全量套件 2 failed 的裁决闭环：1) test_enforce_identity_match_ok 失败详情显示 cwd_match=False + venv PYTHONPATH 锚定主仓 .releases → worktree+共享 venv 环境固有，P0 基线 job（p0 worktree 同 venv）同款失败即对照成立；2) ratchet（静态 scan_tree(src) vs baseline JSON）单跑通过+全量失败时先想运行期副作用，但本案相反——全量时 baseline 尚未同步（mcp_client→mcp_transport 签名迁移 1→1），修复后单跑即绿；3) 定时续跑唤醒时任务可能已被前一触发轮次完成：先查 git log/reflog 提交时间戳与 schedule 注册时间先后，再查 event_stream 该时间窗的 llm_decide 动作，避免重复提交或误报。重跑全量（--tb=long 落盘日志）确认提交后 1 failed(identity)/6894 passed 为终验。