---
method_id: pending-projection-closes-next-step-set-resolve-by-ref-5716de24161c
name: pending-projection-closes-next-step-set-resolve-by-ref
description: 平台操作（如受管服务重启）完成后用户问'下一步建议'：一次 status/审计回执的 pending_actions 投影（待审演进、恢复门、失败动作及各自 ref）本身就是权威待办枚举。先核已完成操作的身份终态，再逐项按 ref 定点解析，配一次 git status/log 补工作区层事实即停；不把已水合 verified 记录再拿自然语言改写检索，也不靠通用词全库搜索重建待办清单——候选集由回执闭包，搜索面缩成少数 ref 的定点解析。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7f2be023-db54-4395-9854-c784b5295062:224:7ef00c46157969d2c925
evidence_refs: learning:learn:a9188a14f3a6
created_at: 2026-10-20T12:19:36.405107+08:00
updated_at: 2026-10-20T12:19:36.405107+08:00
---
## Trigger
一段平台受管操作（重启/发布等）刚完成，用户开放式地问'下一步建议是什么'，且一次 status/审计回执的 pending_actions 块已列出待办工作项（待审阅演进、压缩恢复门、失败动作）及其稳定 ref/会话 ID。

## Discriminator
回执在手即可用：pending_actions 块已给出待办计数、hint 语义（如 escalated 与 degraded 之分）和每项稳定 ref（session_id/manifest_ref）；且已水合记录直接打印 experience_ref + verification_state=verified。这些起点即在手的事实足以把'下一步'候选缩成逐 ref 解析，无需再用改写查询或全库文件搜索重建枚举。

## Short path
- 从审计/status 回执读身份字段（action_id、generation、git_head、pid、succeeded_at），核对与 live 进程/本地 HEAD 一致，关闭'重启是否真完成'这唯一前置未知量。
- 同一回执的 pending_actions 块即待办候选集：对每个 ref（待审演进、escalated 恢复门）按 ID/精确 ref 定点检索解析内容，不重新枚举。
- 回执覆盖不到的工作区层事实（未跟踪目录、近期提交/发布草稿上下文）用一次 git status/log 类廉价枚举补全。
- 每项待办解析到一条权威事实后按影响面排优先级输出，停止发现动作。

## Stop conditions
- 已完成操作的身份核验通过，且每个待办项都已回指到一条权威事实（记录内容或明确状态）。
- 用户选定某一项后转入该专项工作，不再对待办清单做第二遍发现。

## Verification
- 最终建议的每一项都能回指到回执列出的 ref 或一次工作区枚举输出。
- 已 verification_state=verified 的记录未被零命中的改写检索重复推导。

## Counterexamples
- pending 投影只覆盖平台内部待办：用户域遗留（未跟踪调研目录、未绑定 tag 的发布草稿）仍需独立的 git/工作区枚举通道，不能只信回执。
- 用户问的是领域问题（如何实现/诊断 X）而非'接下来做什么'时，pending 枚举与答案无关。
- 某待办 ref 无法直接解析（opaque ID、store 命名未知）时，才升级到 handler/存储源码定位类宽发现。
