---
method_id: runtime-introspection-over-source-scan-for-live-version-check-41be7d0a8ab8
name: runtime-introspection-over-source-scan-for-live-version-check
description: 当需要判断『自己所在运行时即将调用的工具/闸门运行的是新代码还是旧代码』时（服务刚重启、多进程版本不一致、仓库含大量历史 release 副本），不要用文件名全库搜索或逐层 grep 源码来推断。先做运行时自省：查进程版本回执（git_head/code_current）确定哪个进程服务当前会话，再读活体工具 schema，把参数面与预期新特性比对。活体 schema 是『运行进程实际加载了什么』的权威证据；源码搜索只能证明『存在哪些代码』，且 .releases 历史副本会让搜索超时且结果歧义。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80246fde-e7ed-4d85-a591-1327907b29de:548:50c8c14402c0baaa9e43
evidence_refs: learning:learn:5ca249446ae0
created_at: 2026-10-18T12:45:40.437895+08:00
updated_at: 2026-10-18T12:45:40.437895+08:00
---
## Trigger
运行时刚经历代码更新或服务重启（多进程版本可能不一致），且任务关键操作（如准入闸门、发布点击）依赖『即将调用的工具是否已运行新实现』，必须先确认生效版本再执行。

## Discriminator
进入宽搜索之前，进程版本回执已显式给出各服务 git_head 与 code_current 标志（web=当前 HEAD 且 true，cli/feishu=旧且 false），并且环境提供 get_tool_schema 这类活体自省工具——这两条当时已知事实即可把『全库搜源码』缩为『查进程回执 + 读一次活体 schema』。

## Short path
- 读进程版本回执，确认服务当前会话的进程 git_head 与 code_current 标志（未知量：哪个进程服务我的调用、是否已加载新代码）
- 对关键工具调用 get_tool_schema 取活体参数面，与本次更新预期引入的新参数/新描述比对（未知量：运行进程暴露的是新实现还是旧实现）
- schema 含新特性即确认新代码生效，直接沿被点名的运行手册/STATUS 文档继续执行，不重读源码
- 仅当服务进程回执显示 stale、或 schema 歧义时才回退源码核验，且只读回执中 git_head 精确 pinned 的那一份代码路径，绝不做全库文件名搜索

## Stop conditions
- 活体 schema（或等价运行时版本回执）已确认新实现在服务进程内生效，且时间线一致（重启时刻早于当前调用）
- 若怀疑 schema 描述滞后于实现，一次行为探针（带新参数 dry-run 看区分性校验回执）确认后即停

## Verification
- get_tool_schema 返回的参数/描述包含本次更新引入的新字段且措辞与预期一致
- 进程回执 git_head == 当前 HEAD 且 code_current=true，重启时间戳早于本次调用
- （可选）无害行为探针返回新校验特有的错误码/回执

## Counterexamples
- 问题不是『哪份代码在跑』而是『代码内部逻辑或隐藏上限是什么』（如字节硬上限、绑定算法）——schema 看不到内部实现，必须读源码，本方法不适用
- 工具由另一进程或远端服务执行、schema 由本地代理暴露时，本地 schema 不能证明远端版本，需远端自身版本回执或直接行为探针
- 本来的任务就是定位文件（仓库无历史副本干扰）时，普通文件名搜索是正确手段，不必绕道自省
- schema 描述可能滞后于实现（文档陈旧），不能只凭描述断言行为，需配合行为探针
