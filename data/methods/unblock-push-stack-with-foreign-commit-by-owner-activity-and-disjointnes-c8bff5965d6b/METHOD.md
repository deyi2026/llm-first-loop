---
method_id: unblock-push-stack-with-foreign-commit-by-owner-activity-and-disjointnes-c8bff5965d6b
name: unblock-push-stack-with-foreign-commit-by-owner-activity-and-disjointness
description: 多会话共享仓库里推送被卡时，若未推送栈中夹着另一会话的提交，解锁决策不靠翻会话历史/evidence 库（其回执自标 freshness=stale/historical_only，答不了当前态问题），而由两个权威当前态面一次测得：fetch 后的 unpushed 清单（自带提交归属）＋协调面 goal 活跃度（作者会话还在不在推）。作者不活跃、改动面不相交、且审查面为 origin/main..HEAD 全树差异时，接手路线最优：独立验证外来提交（读 diff＋跑其子系统测试）后两提交一起过审一次推送；相交或作者活跃则 rebase 分推/留给原会话。
aliases: 别人的提交堵在没推的栈里怎么解锁, 本地领先远端还夹着他人提交，一起推还是分推, 要不要帮其他会话把提交带上一起推, 推送卡在别的会话的提交上，等不等原作者, 接手验证外来提交再统一推送, 谁的提交谁推吗
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4aea0dd4-3b3b-4874-8090-870678230df3:273:de085c329b9a5bb3e651
evidence_refs: learning:learn:cad1c376a9b2
created_at: 2026-11-02T23:50:23.721973+08:00
updated_at: 2026-11-02T23:50:23.721973+08:00
---
## Trigger
多会话共享仓库中，本地领先共享远端的未推送提交栈里夹着另一会话的提交（自己的提交叠在其上），推送/收口被卡，需要决定等待、接手携带还是绕开分推；常出现在极简『下一步建议/继续』且任务状态回执为 not found 的续跑场景。

## Discriminator
fetch 后的 unpushed 清单本身携带归属信息（提交作者/消息可区分会话），配合协调面各 goal 的 owner 与最近活动时间即可判定：外来提交的作者会话是否仍活跃（等不等得来解锁、决定权在谁）；再由两提交 diff 文件集是否相交、审查面是否为 origin/main..HEAD 全树差异，判定『一起验证一次推』是否成立。evidence 回执自标 historical_only 明示它答不了当前态。

## Short path
- 续跑/建议请求且任务状态回执 not found：不在 evidence 库换措辞翻会话历史，直接 fetch 并取 HEAD、origin tip、unpushed 清单；未知量＝当前阻塞差与每笔提交归属
- 读协调面各 goal 的 owner 与最近活动时间戳；未知量＝外来提交的作者会话是否仍在活跃推进、解锁决定权在谁
- 作者不活跃＋改动面不相交＋审查面=全树差异 → 接手路线：读外来提交 diff＋跑其子系统测试独立验证；未知量＝能否安全携带
- 验证绿则两提交一起过审一次推送；改动相交/验证可疑/作者活跃则转 rebase 分推或留给原会话，停止继续枚举
- 推送前按既有门禁核对（CI 对当前树预期、publish 的干净树要求），收口时观测对应审计事件是否出现

## Stop conditions
- 已判定解锁路线并落地：接手携带（验证绿＋单次审查推送完成）或明确分推/留给原作者，不再枚举其他可能性
- 协调面显示外来提交作者会话活跃推进（tasks 有 doing 或 last_cp 新鲜）→ 不接手，转等待或点对点协调

## Verification
- unpushed 清单中每笔提交的会话归属有提交作者/消息佐证，不凭记忆断言
- 携带验证＝外来提交 diff 已读且其子系统测试全绿
- 推送后 origin/main tip 与本地 HEAD 一致，且推送前已核对 CI 对当前树的预期

## Counterexamples
- 外来提交作者会话仍活跃（协调面 last_cp 新鲜、有 doing 任务）→ 等它自己推，接手反而制造双写/双推冲突
- 两提交改同一文件或同一语义面 → 不相交前提破坏，『一次推送天然覆盖』不成立，需 rebase 分推或显式协调
- 用户问的是历史动机（当初为什么这么改）→ 权威面是 evidence/设计文档，git delta 答不了
- 单人仓库或无推送审查门禁 → 无审查面覆盖论据，直接推送即可，无需归属裁决
