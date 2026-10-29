---
method_id: invalid-object-fatal-voids-ancestry-label-rerun-where-refs-resolve-be127aa9dece
name: invalid-object-fatal-voids-ancestry-label-rerun-where-refs-resolve
description: 跨工作副本/克隆对两个 git 引用下结构性结论（是否祖先、能否 ff-only、领先/落后多少）时，比较必须在双方引用都能解析的同一仓库里执行。判别信号：回执同时出现结论标签（NOT_ANCESTOR/NOT_FF）与 stderr『fatal: Not a valid object name <sha>』，fatal 证明该对象不在被查询仓（如 dev worktree 独有提交从未同步到 mirror），标签只是脚本 echo，比较根本没执行，照标签行动会得出假分叉。正确动作：到已含双方对象的仓库（通常是合并过对侧的 worktree）-C 定点重跑 merge-base --is-ancestor / rev-list --count，以 exit code 为准；要写进交接/报告的结构性事实必须来自无 fatal 的回执。
aliases: not a valid object name 还能信 NOT_ANCESTOR 吗, 跨仓库在哪边跑 merge-base, mirror 里查不到 worktree 的提交, 快进可行性检查在哪个仓执行, 交接里的 can-ff 结论怎么核实, ff-only 前置检查 fatal 无效对象
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:3541:ad3928e80899ebb3ec87
evidence_refs: learning:learn:493073b6ee0a
created_at: 2026-10-28T15:38:07.793013+08:00
updated_at: 2026-10-28T15:38:07.793013+08:00
---
## Trigger
需要在两个 git 引用之间得出结构性结论（祖先关系、ff 可行性、ahead/behind 数），而两个引用分属不同工作副本或克隆（dev worktree、生产 mirror、release 快照仓），其中至少一侧提交从未 fetch/push 到对方仓库

## Discriminator
回执中结论标签与 fatal 并存：stderr 出现 `fatal: Not a valid object name <sha>`，且更早回执已显示该 sha 是另一个工作副本的 HEAD。fatal 意味着本次比较未执行，任何 NOT_ANCESTOR/NOT_FF/ahead 计数对该问题都是无效输出

## Short path
- 从已有回执确认两个 sha 各属哪个仓库、哪个仓已同时含双方对象（如分支 log 里存在合并对侧 main 的提交，则开发 worktree 即可判）
- 在持有双方对象的仓库 -C 定点执行 merge-base --is-ancestor 与 rev-list --count，一次取得 ff 可行性与领先数
- 对侧仓库只查它自己的 HEAD 与工作区干净度，不做跨仓引用比较
- 仅当回执 exit code 明确且无 fatal 并存时，才把结构性结论写入交接/报告

## Stop conditions
- 在双方引用均可解析的仓库中拿到 exit code 明确的 ancestry/计数结果，即停止换仓重试
- 若检测目的本来就是『对方仓库是否知道该提交』（如 push 是否生效），invalid object 本身就是答案，不再换仓

## Verification
- 对将进入交接的每条 git 结构性事实复查两点：执行仓是否能同时解析双方引用；回执中不得出现 fatal 与结论标签并存

## Counterexamples
- 两个引用在同一仓库（比较本仓分支，或 fetch/push 之后）：NOT_ANCESTOR/NOT_FF 是真实裁决，应照常据此规划合并策略
- 目的是验证 push 是否已生效：远端不认识该 sha 恰是要检测的事实，不是查询姿势错误
- 对象理应存在于本仓却报 invalid object：属浅克隆/仓库损坏/需 fetch 修复的问题，换仓执行不解决
