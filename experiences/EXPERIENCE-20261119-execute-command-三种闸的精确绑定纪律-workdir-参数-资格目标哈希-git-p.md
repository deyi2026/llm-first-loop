---
title: execute_command 三种闸的精确绑定纪律：workdir 参数、资格目标哈希、git_push/full_test 分种类
scenario: LFL 宿主命令闸+资格闸下的受管 lane 合并链：文件写入、git add/commit/push、ci_gate R9、PR 合并队列全流程（2026-11-19，会话 d901b48e，lane-cae63ab4）
root_cause: ""
solution: 见 body 三条纪律
evidence: "job-5de20985e6fd4fe7ab63(主仓 dirty=81 触发知识闸,workdir 参数缺位)；job-316163bc8b04471abac0+lane_record v11(via cd)；STAGED_CHECK_EXIT=128 index.lock EPERM(workdir=隔离树写主仓.git)；target_mismatch 拒绝(ci_gate|tail 改写命令文本)；parent_mismatch(64c99558 full_test 资格跨会话拒)；lane_queue_submit mq-2601d1e8 S0 全过+PR#74 checks 全 SUCCESS+merge 4075358a+lane 自动 merged v16"
tags: [execute_command, workdir-param, review_admission, target-binding, git-push, lane-queue, github-protection-strict]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-19T21:22:29.672813+08:00"
updated_at: "2026-11-19T21:22:29.672813+08:00"
---

三条 2026-11-19 实测纪律（Issue73 lane-cae63ab4 合并链，全部真实回执验证）：
1) execute_command 的 Host 预检（知识闸/lane 主写守卫）读取工具独立参数 workdir，不解析 shell 字符串里的 cd。写文件类命令须显式 workdir=目标树（隔离树 pending=0 即过知识闸）；git 变更类在共享 .git 场景用 workdir=主仓 + `git -C <worktree>`（守卫解析 -C 目标分支）。workdir=worktree 参数会收窄写 scope，主仓 .git（index.lock/refs/remotes）EPERM——两种姿势按写对象选择。
2) review_admission 资格绑定精确命令文本+workdir：`bash scripts/ci_gate.sh | tail` 会因管道改写命令哈希 target_mismatch 被拒（资格不消费）；受管动作必须以与 start 完全一致的裸命令发起。git_push 与 full_test 是独立资格种类，各自需独立审查 PASS，且不跨父会话消费。
3) GitHub 保护 strict=true + 无 merge queue 时，PR 合并前必须把最新 main 无冲突合入分支（disjoint 路径验证 OVERLAP=0 后 ff/merge），合并 SHA 重走 A.5/Reviewer/R9/CI 全链；三-dot diff（base...head）使合入后 A.5 覆盖面自然收敛到本 lane 7 路径。合并后 lane_queue_confirm(done, merge_commit) 会触发 lane 自动落终态 merged（治理③），无需手动 lane_close。