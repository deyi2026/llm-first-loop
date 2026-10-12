---
title: 次级 worktree 跑 llm-first-loop 全量单测：runtime identity 守卫测试按设计失败，需主树/pristine 双对照判定
scenario: 在 llm-first-loop 镜像仓库的次级 git worktree 中运行全量 unit 测试套件，评估改动回归状态
root_cause: ""
solution: 先在主树（runtime root）复跑同一测试；再建零改动临时 worktree（同 commit --detach）复跑对照。主树过 + pristine worktree 也挂 ⇒ 环境固有，与本改动无关，单列说明即可；不据此改动守卫或放宽基线。
evidence: "evidence://v1/81f8bdd41c2aa08bbee647156309dd7318ee73a3822cec8f2fbfcee069d80964（worktree 失败+主树通过双跑回执）；evidence://v1/4ca3cdca04b73eea918597ebdeb9338420e147146fb6127cfb9be70764453311（env -u PYTHONPATH 仍失败）；pristine worktree 对照复现（execute_command 回执，2026-10-09T09:54，1 failed in 0.06s）"
tags: [llm-first-loop, worktree, pytest, runtime-identity-guard, mirror-testing]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-09T09:55:23.393427+08:00"
updated_at: "2026-10-09T09:55:23.393427+08:00"
---

2026-10-09 在 llm-first-loop-mirror 次级 worktree（.worktrees/p0-mcp-adapter-20261009，commit c825ad890）跑 tests/unit：6860 passed，仅 test_runtime_identity_enforce.py::test_enforce_identity_match_ok 失败；同一测试在主树通过。用零改动临时 worktree（git worktree add --detach a64e18b74）复跑仍失败，证明与代码改动无关，是守卫按设计比较 cwd 与运行时根所致。其余测试不受影响（pytest ini pythonpath=["src"] 相对 rootdir 优先解析；新增 P0 行为测试通过即证明导入来自本 worktree）。后续在镜像 worktree 跑全量套件时，此项失败按环境固有处理，不做基线放宽，也不用它判断改动回归。