---
title: "审计共享仓库里\"代理自主合 main / stash 他人改动\"的取证口径（作者身份 + 一阶链 + 回执 sha 三查）"
scenario: "多代理（人类会话 / DSH 外部代理 / MCP 控制台）共享同一 git 仓库与 main 工作树，需要判断是否发生过\"代理自行把分支合入 main\"或\"某方 stash 掉他人未提交改动\"。"
root_cause: ""
solution: "按三查取证：①作者身份映射（git log main --pretty='%an' 分布 + git config --list --show-origin 里的 local/global user.name + 其他克隆的 local 身份），把\"代理侧身份\"与\"人类/父会话身份\"分开；②方向判定（git log --first-parent 看该 merge 是否真落在 main 主干一阶链上，再看 %p 的第一/第二父分别属于主干侧还是分支侧，区分\"分支→main\"与\"main→分支同步\"）；③闸覆盖核对（把回执里 main_sha_after / 正文出现的 sha 与 main 一阶 merge 列表做交集，未被任何回执文本提及的 merge 计为闸外落库）。stash 侧另查 git stash list 的 %cn 与 stash 说明文字，区分\"为解阻塞而自 stash\"与\"stash 他人产物\"，并核对当前工作树脏文件与 stash 文件的交集作为未来 pop 冲突面。注意 RULE-AI-34 合并闸是模型侧纪律（无程序强制），程序强制只落在 push/全量测试闸（review_admission kind=git_push），因此\"闸覆盖缺口\"要以回执文本与 sha 交集为准，不能以\"规则已写\"推定已生效。"
evidence: "llm-first-loop-mirror 实测：main 一阶链 2026-10-17 后 25 个 merge 中仅 7 个 sha 被 docs/governance/receipts 文本提及（3bd8f3096 等）；1fd9f0357(syagi-agent, 2026-08-16, 分支→main 方向, p1=0ff907578/p2=cf6554d8d) 无任何回执；bfa9d7982/d1c9d64dc 为 main→分支同步方向；git stash list 24 条全部 %cn=deyi2026，说明含\"止血快照: 并发写收束 tracked=336\"、\"stashed to unblock deployment binding\"等解阻塞式 stash；git config --show-origin 显示 global user.name=syagi-agent、本仓库 local=deyi2026、llm-first-loop-public local=syagi-agent"
tags: [git, 审计, 双代理, 合并闸, stash, 并发写者]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T18:50:41.952685+08:00"
updated_at: "2026-10-31T18:50:41.952685+08:00"
---