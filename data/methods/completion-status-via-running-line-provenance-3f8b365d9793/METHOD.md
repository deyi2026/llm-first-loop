---
method_id: completion-status-via-running-line-provenance-3f8b365d9793
name: completion-status-via-running-line-provenance
description: 当用户问某项工作'完成了吗'且环境是逐代部署+多 worktree 时：先锚定运行线身份（部署回执的 git_head/generation），用 vcs 溯源（worktree/分支/commit 祖先关系）定位该工作位置与阶段，以该工作自带的设计文档/commit 正文界定范围，再用运行态工件（audit/ledger 的行数与进程来源）验证是否真上线。不要先在 runtime 工作区 grep 源码表面——那反映本地检出分支，不是部署线。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:516:2c2d1dbf3ee3c14cdb8a
evidence_refs: learning:learn:8c325258eb76
created_at: 2026-09-17T15:25:44.697780+00:00
updated_at: 2026-09-17T15:25:44.697780+00:00
---
## Trigger
用户询问某功能/工作项是否完成、是否已上线；部署为逐代演进（回执给出 pinned git_head 与独立 code_root），代码可能分散在多个 branch/worktree

## Discriminator
部署回执已把 code_root（部署线，固定 head）与 runtime_root（工作区）分开，且运行态审计/ledger 若只有开发测试进程写入（少量行、测试 pid），即可断定观测未在生产收集——此时下一个未知量是'该工作在 vcs 哪里、是否在运行线祖先链上'，而不是'源码注入面长什么样'

## Short path
- 取部署回执，确定运行线身份（generation、git_head、code_root worktree 路径）
- 探运行态工件尾部（audit/ledger）：区分开发进程写入与生产写入，判断统计是否已开始收集
- git worktree list + 近期分支/主题过滤：定位该工作的候选 commit 与配套设计文档
- 读该分支的设计文档/commit 正文：取得分层、分期、范围结论（权威来源，替代源码表面 grep 枚举）
- 祖先检查：候选 commit 是否在运行线 head 历史内；输出逐阶段状态（已编码未合并/已合未部署/已部署未收集）并停止

## Stop conditions
- 每个阶段的'已上线/未上线'断言都有双证据：vcs 祖先关系（对运行线 head）+ 运行态工件是否真实写入
- 范围类问题（哪些常驻、哪些按需）已由该工作自带设计文档回答，不再枚举源码表面

## Verification
- 最终结论中每个上线状态断言可回指部署回执 git_head 的祖先链检查结果
- 统计类断言（如生产注入数=0）由 ledger 行的进程来源与行数支撑
- 若工作区 grep 所见文件与部署线 head 不一致，以部署回执+祖先关系为准重新校验

## Counterexamples
- 单 worktree、部署即当前检出的仓库：无逐代部署回执，直接查 HEAD+CI 即可，套用反而绕远
- 用户问的是设计问题（'应该怎么分层'）而非完成状态：直接读设计文档，无需 vcs 祖先核对
- 工作只存在于未提交的本地改动：vcs 溯源找不到，必须回到工作区 status/diff 与源码枚举
- 运行时被热修（实际运行代码 ≠ 部署 head）：祖先关系会误导，须以运行时回执/行为异常为准
