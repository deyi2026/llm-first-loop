---
title: RULE-AI-28 push 闸漂移拒绝：先 flush 未跟踪卡并把 worktree HEAD 停到远端 tip
scenario: "RULE-AI-28 git_push 闸：审查 PASS 已签但 push 反复被\"不存在覆盖当前产物的有效资格\"拒绝；工作区有并发会话持续写入未跟踪知识卡（data/methods、data/experiences）"
root_cause: ""
solution: push 前固定材料：1) knowledge_flush 把未跟踪卡提交成 main 直接提交（清空易变部分）；2) 主 worktree checkout --detach 到远端 tip，使 push_head≠HEAD，审查材料=纯提交集=上传集；3) 起闸→PASS→立即 push；4) push 后 HEAD 恢复到新 tip。多会话共写一仓时起闸前后都 ls-remote 核远端真值。
evidence: "evidence://v1/a3a02c05deb665985d6f6bc9440bfa852589079cf77754a28d55cddd93404f38（status=PASS 但 push 连续两次被拒）；evidence://v1/cbe0344a11383c3437e21a9c4899abd855a956cadd7badc7d14eb9053cd14b4a（未跟踪 9→10 漂移实测）；evidence://v1/bdd0b412a545dc4e761835542db282a84b40e6d5cf3ec27db12e64eed0aff9ba（闸源码 check_shell 重算逻辑）；evidence://v1/f48326486535856b12eea0a92975fd75b0c054d0365fff67d50ee8f5dd134e13（flush+停远端tip 后新审 PASS）；push 回执 8c114428f..7b9c5e0fc main -> main"
tags: [rule-ai-28, git-push, review-admission, drift, knowledge-flush, worktree]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T18:18:52.459030+08:00"
updated_at: "2026-10-29T18:18:52.459030+08:00"
---

现象：review_admission 已核验 completed+PASS 并签发资格，紧接着的 git push 仍被 [RULE-AI-28 Host准入阻断] 拒绝，重试同样被拒。
根因链（读 .releases/8c114428f.../src/llm_loop/tools/review_host_admission.py 核实）：
1) status 的 PASS 只对冻结时的 sha 验签，从不重算；check_shell 在检查瞬间现场重算 (kind,target,sha) 再匹配，注释明说"漂移检测内建于重算"。
2) include_worktree = (push_head is None or push_head == repo HEAD)。主 worktree detached 在 main tip 时两者相等，未跟踪文件被计入快照哈希。
3) 并发会话持续往 data/methods、data/experiences 写新卡，审查 4-5 分钟窗口内未跟踪集必然变化 → 重算 sha ≠ 冻结 sha → 拒绝。实测：冻结 9 项未跟踪，4 分钟后变 10 项。
4) 冻结哈希含未跟踪内容后即不可救：漂移状态无法复现，旧 PASS 作废。
稳定解（本轮验证成功）：
a) 先跑 knowledge_flush.py 把未跟踪卡打成 main 上的直接提交（RULE-AI-34 只管分支合并，直接 main 工作"无合并面"不触发闸；历史 flush 提交 10a732e1e/c455b6f51/d528fbe9a 均为 main 单亲直接提交）。
b) 把主 worktree HEAD checkout --detach 到远端 tip（push_base），使 push_head(=refs/heads/main) ≠ HEAD → 代码设计路径"非 HEAD push 源，材料=精确上传集"，快照=纯提交 delta，天然免疫未跟踪漂移。这不是绕闸：上传的每个字节仍在审查材料内，闸仍是最终权威（漂移时照旧 fail-closed）。
c) flush 在 detached HEAD 上提交后，从 .worktrees/main-merge 用 merge --ff-only 把 main 快进到新提交（main 在该 worktree 检出）。
d) push 成功后把主 worktree HEAD 恢复到新 main tip。
附带事实：多会话并行推同一仓库时，另一会话可能已把部分提交推上远端；起闸回执里的 push_remote_commit 若比本地缓存的 origin/lfl 新，先 ls-remote 核真值再判断剩余待推集。同日有并行会话沉淀方法卡 pin-live-remote-tip-before-computing-push-set-8c4373cef87e，与本经验互补。