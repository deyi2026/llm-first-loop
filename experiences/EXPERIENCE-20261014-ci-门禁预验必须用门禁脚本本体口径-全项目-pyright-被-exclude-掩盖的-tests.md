---
title: CI 门禁预验必须用门禁脚本本体口径：全项目 pyright 被 exclude 掩盖的 tests 诊断在 scoped 运行下暴露
scenario: "任何带 ratchet/gate 脚本的仓库：验证\"push 后 CI 门禁会不会绿\"时，本地复现必须走门禁脚本本体（含其 changed 集定义与工具调用方式），而非自己另起工具命令。"
root_cause: 用旁路工具口径（全项目 pyright 自动发现，受 exclude 影响）验证 CI 门禁结论（scoped 文件运行，不受 exclude 影响），两者检查面不同却当作等价证据使用。
solution: "1) 本地预验 CI 门禁一律直接运行门禁脚本本体（如 `python scripts/check_static_diagnostics.py --tool pyright`），在干净 detached worktree（零 uncommitted/untracked）上跑，与 CI 检出同构；2) 旁路工具结论（全项目 pyright/ruff）只能作参考，不得作为门禁放行证据；3) 注意共享工作树上门禁会把他人未提交文件算进 changed[uncommitted] 集导致本地误红——需区分 committed 集与 uncommitted 集再下结论；4) scoped 运行时 pyright exclude 不生效是关键机制。"
evidence: "审核 FAIL 复现 evidence://v1/39b7af9e74aab713bbe4fca3fa7be9e995a2deadd3dc51be356da6b142e1329d（后续轮次）；独立复现 3 errors evidence://v1/8bb3e9787f65fa2488cad7f3db1afc2ab421c8c186ea686f75e8aa099eef0a44；门禁三绿 /tmp/gate-clean.log；复核 PASS evidence://v1/6b07d6fcbd2043791a398635100b478c4e195150c68bccc728b3db53ddb13dcd；push 成功 evidence://v1/fd3b5917095f8533b5ebeaec1877cf961aee9682f6cd5aa40e125f25dd36bde3"
tags: [ci, pyright, ratchet, verification, gate, worktree]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-14T18:38:24.709744+08:00"
updated_at: "2026-10-14T18:38:24.709744+08:00"
---

CI pyright ratchet 门禁（scripts/check_static_diagnostics.py）对 changed 文件做 scoped pyright 运行，pyrightconfig 的 exclude 不适用于显式指定文件；而直接跑 `pyright`（无参数，全项目自动发现）时 tests/ 被 exclude 跳过。上轮我用全项目运行得出 "pyright PASS changed_file_diagnostics=0"，实际该测试文件存在 3 条 reportOptionalMemberAccess，push 后会触发 'changed files must have zero diagnostics' DENIED。审核子代理以门禁同口径（冻结版 1.1.411 + scoped 文件运行）复现出 3 errors，FAIL 阻塞成立。修复：1424b671d 对 read_action() 两处结果补 is not None 断言；干净 worktree 以 check_static_diagnostics.py 本体跑出三绿后复核 PASS，push 成功。