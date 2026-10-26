---
title: Rule-28 review gate 的 candidate sha drift-check 机制与排障路径
scenario: "review_admission PASS 后执行 push 仍被拦\"不存在有效独立审查资格\"，需要定位原因（多会话并行操作同一仓库）。"
root_cause: ""
solution: 该拦截的常见原因不是资格未签发，而是 candidate 漂移：审查冻结后（其他会话）rebase/checkout/commit/远程 ref 移动都会改变 _source_snapshot 的 identity（组成：head、frozen_head、base、material、repo、untracked_shas）。处置：先 git rev-parse HEAD + git reflog --date=iso 查窗口期变化 + ls-remote 查远程；确认有并行写者时应停止重试（重试只会再烧审查资格），回到观察或协调。验证指纹可手动调 _push_target/_source_snapshot 对比冻结值。
evidence: "源码 review_host_admission.py:1550-1561 check_shell 重算注释\"if the remote ref moved after admission, the candidate SHA changes and the grant will not match\"；实测冻结 3ea21e6c vs 重算 9617d50a；两次阻断回执。"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-22T23:18:44.373208+08:00"
updated_at: "2026-10-22T23:18:44.373208+08:00"
supersedes: [EXPERIENCE-20261022-rule-ai-28-push-闸的-同一目标-约束-复合命令必被拒-逐字单命令放行]
---

正例实证：接管者对 StateBraid 发起 review_admission(start, git push b2fbe45:main) 得 PASS，但另一会话在窗口期内 rebase 改变仓库 HEAD，两次执行 push 均被拦截。检查 llm-first-loop-mirror/src/llm_loop/tools/review_host_admission.py 确认：check_shell 每次重算 _source_snapshot（含 HEAD/base/material/untracked），四元组(parent,kind,target,sha) 全等才放行，drift 检查内建于重算。