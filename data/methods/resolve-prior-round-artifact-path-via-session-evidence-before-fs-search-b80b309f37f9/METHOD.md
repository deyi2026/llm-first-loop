---
method_id: resolve-prior-round-artifact-path-via-session-evidence-before-fs-search-b80b309f37f9
name: resolve-prior-round-artifact-path-via-session-evidence-before-fs-search
description: 续轮/恢复会话中，用户用回指性说法（『这份报告』『上次那份审查』）要求修改或跟进一个上一轮已读过的文档时，不要对该文件重新发起文件系统 glob 或内容搜索——大仓库下内容关键词常 miss 甚至超时。先查会话内已持久化的通道：按内容关键词检索证据库、或恢复最近保存的任务状态；上一轮的读取回执自带精确路径与 freshness 元数据，一次命中即可直接用该路径，再配 evidence 分页读全文。
aliases: 上轮读过的文件直接查证据库, 全仓库搜索超时先翻历史回执, 续会话找报告别重新搜, 回指文档先恢复任务状态, 找不到上次那份报告怎么办
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:349:38a1e703edd13cda6dc9
evidence_refs: learning:learn:6f8d121e82b4
created_at: 2026-10-29T00:22:15.024554+08:00
updated_at: 2026-10-29T00:22:15.024554+08:00
---
## Trigger
续轮或断点恢复的会话中，用户指令回指一个前轮已处理过的 artifact（报告/文档/补丁），且当前未知量是该 artifact 的确切路径或内容范围

## Discriminator
用户回指的是本会话或紧邻前轮已读过的对象，且模型记得读过——则证据库中必有带精确路径的 read 回执、task state 中往往也存了该路径；这把『全仓库哪个文件』缩成一次证据检索即可判别

## Short path
- 环境参数报错（如 workdir 无效）时，先用一次 pwd && ls && git rev-parse --show-toplevel 钉死真实工作区，未知量：我在哪个仓库
- 对回指 artifact，先 search_evidence（内容关键词）或恢复最近 task state，未知量：它的精确路径与新鲜度
- 命中 freshness=verified_current 的读取回执后直接采用其路径，不再做文件系统搜索；未知量：内容是否最新
- read_file 只返回首屏时，改用 evidence hydration 按 range 分页读取目标段落，随后进入编辑/执行
- 读取回执的行数、标题与回执元数据核对一致后停止发现

## Stop conditions
- 已从证据回执取得 verified_current 的精确路径，且行数/标题与用户回指对象吻合
- 证据检索与 task state 均无该对象记录 → 此时才降级为文件系统搜索或直接向用户要路径

## Verification
- 回执 freshness=verified_current 且 workspace_path_state=current_match
- 分页读取的 range 覆盖报告声明总行数（如末页 complete:true）
- 对同一文件不重复发起第二次全仓库内容搜索

## Counterexamples
- 用户引用的 artifact 从未在本/前轮读过（证据库无记录）→ 证据优先不适用，应走文件系统发现或直接询问
- 证据记录已 stale（文件被移动/改名）→ probe 失败后应回退文件系统枚举，而不是反复换词查证据
- 全新一次性任务、无会话历史可回指 → 不存在该通道，正常发现流程
