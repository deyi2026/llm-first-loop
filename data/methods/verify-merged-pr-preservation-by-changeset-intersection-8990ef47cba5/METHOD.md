---
method_id: verify-merged-pr-preservation-by-changeset-intersection-8990ef47cba5
name: verify-merged-pr-preservation-by-changeset-intersection
description: 任务点名核验『已合并 PR 的改动在新候选中被保留/未回退』时，不要对整树 grep 特性关键词枚举相关文件、也不要去证据库搜旧会话描述：先从 git 合并历史取出各 PR 的变更文件清单，与候选 diff 路径集求交。交集为空即由构造证明未动（补一条这些路径 base..HEAD diff 为空复核）；仅交集非空的共享文件（如 factory.py 同时承载特性接线）才升级行级检查：候选 diff 中特性 token 无增删 + HEAD 引用计数仍在。『保留』是集合运算命题，不是全树发现命题。
aliases: 旧PR改动有没有被新分支覆盖, 先查PR改了哪些文件再对比候选, 验证上游修复未回退, 基线保留用集合运算别全树搜, merged PR preserved check
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a43dc767-17c2-429a-82f3-1dd9d4aa5558:158:02954105712d8d1450fd
evidence_refs: learning:learn:5228ca94791e
created_at: 2026-11-15T21:59:18.765011+08:00
updated_at: 2026-11-15T21:59:18.765011+08:00
---
## Trigger
新候选基于命名 base commit 重建，任务书按 PR 编号/名称点名要求验证既有已合并改动（observer、CI 修复等）未被触碰或回退；git 历史可解析这些 PR 的合并提交；候选变更路径集已可由 git diff 取得。

## Discriminator
首条 git 回执已同时给出：base 为候选 HEAD 祖先 + 候选精确变更路径清单；任务文本已给 base commit 身份与被点名 PR。这两组路径清单的交集当时就足以判定『保留』，整树关键词枚举不提供额外判别力。

## Short path
- 一条 shell 取齐候选事实：HEAD/branch/porcelain/base 祖先 + git diff --name-only base..HEAD → 候选路径集（未知量：候选身份与精确范围）
- 从 git 历史取保护集：对每个点名 PR 用其合并 commit 的 first-parent diff --name-only 得到该 PR 变更文件清单（未知量：该 PR 到底改了哪些文件）
- 求交：交集空 → 保留由构造成立，补 protected 路径 base..HEAD diff 为空复核；交集非空 → 只对共享文件做行级判定（候选 diff 中特性 token 无增删、HEAD 特性引用仍在）
- 读提交 manifest/治理声明，核组件路径并集 == 候选路径集（未知量：声明覆盖与实际 diff 一致）
- start 准入：回执核对 accepted、paths_ignored=false、scope.paths 与本地清单逐条一致、SHA 为新值而非旧 PASS 复用
- 按等待协议轮询至终态；终态再查一次确认稳定后取子代理发现并回报；pending 永不作为结论

## Stop conditions
- 所有点名 PR 均满足：交集为空，或共享文件行级检查干净
- 准入回执 accepted 且 paths_ignored=false、路径精确匹配、candidate_sha256 为新值
- qualification 到达终态且两次查询一致；立即回报，不做任何修复/R9/写操作

## Verification
- overlap 输出字面为空；protected 路径 base..HEAD diff --stat 为空
- 回执 scope.paths 与本地 git diff 路径逐条比对一致
- 终态回执重复查询一致；子代理 FINGERPRINT 与 Host candidate_sha256 前缀一致

## Counterexamples
- 点名改动无可解析的 commit/merge 身份（只有口头描述）→ 集合运算不可用，退回有界关键词/provenance 检索
- 候选 diff 与保护特性的核心文件大量语义相交（不只是共享工具文件）→ 需内容级审查，交集判据不再充分
- 保护对象是运行时状态/迁移数据而非 tracked 文件 → git 文件清单不覆盖，须查运行面
- base 非候选祖先（候选曾 rebase）→ 先对齐 merge-base 再求交，否则交集无意义
