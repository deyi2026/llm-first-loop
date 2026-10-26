---
title: CI 红灯修复：双远端镜像下先在精确提交树本地复现门禁，再修复推送
scenario: 用户报告 deyi2026/llm-first-loop CI 两 job 红灯（安全扫描 46s + 门禁 11s），镜像仓有 lfl 与 origin(legacy) 双远端，且 lfl/main 落后本地 main 12 个提交、本地 main 自身也红。
root_cause: ""
solution: "不要假设\"历史里已有修复(d699b8f6a/1424b671d)推上去就绿\"：其后的 33a64baa5/287421ad7/d1b9f4b76 又新增 ruff x5 + pyright x1 欠账。用 git worktree 在精确提交树复现两个失败 job（ratchet 脚本+安全扫描+pytest 与 CI 同口径），机械修复（UP035/SIM103/SIM108/F401 + detail or None 类型违规）后本地 ratchet new=0 再推送，并轮询 CI 到绿。"
evidence: lfl run 38571975427 success 12m12s；legacy run 38571978222 success 13m24s；本地 ruff ratchet new=0 / pyright ratchet new=0 / scan --tree 5696 files pass / full pytest 8735 passed + 4 flaky（孤立复跑 4/4 过）
tags: [ci, github-actions, ruff-ratchet, pyright, worktree, flaky-tests]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T21:42:15.669274+08:00"
updated_at: "2026-10-14T21:42:15.669274+08:00"
---

1) 先 gh run list 定位失败 run 与其 head commit；镜像双远端时明确用户所指仓库（本次 lfl=deyi2026/llm-first-loop，origin=legacy）。2) git worktree add --detach /tmp/verify <commit> 在精确提交树上复现：scripts/git_security_scan.sh --tree（46s 级）、check_static_diagnostics.py --tool ruff/pyright（ratchet BLOCK NEW/changed_file_diagnostics），.venv 可跨 cwd 复用。3) 修复提交后重跑两个 ratchet 到 new=0。4) 推送后 gh run list 轮询确认 completed success。注意：d699b8f6a 式既有修复不等于当前树绿——必须检查其后提交是否新增欠账；4 个 race 敏感测试在本地并发重载（pyright+扫描同跑）时假红，孤立复跑全过才算 flaky。