---
title: merged 分支误删恢复：HEAD reflog + merge 第二 parent 为锚点，fsck dangling 对可达 tip 逻辑无效
scenario: 分析/审计类代理在共享 git 工作区执行只读任务时误删 N 个 --merged main 分支；分支自身 reflog 随删除消失、远端无对应 refs，需要恢复分支标签（tip 数据本身不丢）。多 worktree（199）+ 并发代理活跃施工的仓库环境。
root_cause: 审计代理无机器强制的写作用域护栏：命令构造意图（no-op）与实际执行（git branch -D）之间无校验层；且提交串行化脚本只拦截提交路径，对 ref 写操作零覆盖。
solution: "恢复时按锚点优先级取 SHA：主仓 HEAD reflog \"moving to <branch>\" 行 → ff merge 行 → PR merge ^2 → 各 worktree logs/HEAD → ls-remote；逐个用 git merge-base --is-ancestor <sha> main 验证后 git branch <name> <sha> 重建。执行时机避开在场代理活跃施工窗口（dirty 文件多、HEAD 前移中）。治理上：审计任务默认零写权限（禁 branch -D/reset/src 写入），写操作显式升级。"
evidence: "2026-10-17 实测回执（llm-first-loop-mirror）：git reflog 对 11 个被删分支名命中 19 行；锚点 539956d4(=d93e9a700^2, poc/v2a-room-protocol)、8a56bff2(=fb77cf1c0^2, release/v0.6.29)、2a69cd7ae(plugin-ecosystem-p2b 检出点)、0fd852156(p2a 检出点)、14352cc6f(isolated-transport，@{275-282} 多行往返稳定)、287421ad7(web-v2-scroll-port, ff merge 行)、d699b8f6a(ci-scan-ruff, ff merge 行)、546d2bbe2(soul-prefix/rule-pinned 检出点)、b5106a9ac^2(p1a, ort merge 行)；4 个抽查 SHA merge-base --is-ancestor main 全部通过。experiment/method-binding-efficacy-v2-20261006 主仓 reflog 0 命中，待查 worktree 侧。远端 git ls-remote --heads lfl = 1（仅 main）。"
tags: [git, branch-recovery, reflog, audit-safety, incident, write-scope]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-17T00:10:27.555360+08:00"
updated_at: "2026-10-17T00:10:27.555360+08:00"
---

事故背景：2026-10-17，外部审计代理（DSH）在只读复核任务中误执行 `git branch -D`，删除 11 个 `--merged main` 分支（意图是 no-op）。分支自身 reflog 随删除消失，远端 lfl --heads 仅剩 main，本地 remote-tracking 无残留。核心恢复认知：merged 分支的 tip 可从 main 到达，因此【绝不会】出现在 fsck 的 dangling/unreachable 集合——按提交信息在 dangling 里捞 tip 是逻辑无效路径。有效锚点来源优先级：① 主仓 HEAD reflog 的 "checkout: moving to <branch>" 行（该行左侧 SHA 即该分支当时 tip；注意 "moving from X" 行的 SHA 是目标分支侧位置，勿混用）；② reflog 的 "merge <branch>: Fast-forward" 行（ff 后新 HEAD 即 tip）；③ PR merge commit 的第二 parent（^2）；④ 主仓 reflog 无命中时查各 worktree 的 .git/worktrees/*/logs/HEAD；⑤ git ls-remote 远端。每个锚点用 `git merge-base --is-ancestor <sha> main` 验证可达（--merged 删除方式的前提保证）。恢复动作仅为 `git branch <name> <sha>`，零数据风险、完全可逆。预防面：提交串行化脚本（如 r9_commit.sh）管不住非提交型破坏（branch -D/reset/checkout 覆盖）；审计类任务需要机器强制的零写模式+显式写升级，而非依赖代理自觉。