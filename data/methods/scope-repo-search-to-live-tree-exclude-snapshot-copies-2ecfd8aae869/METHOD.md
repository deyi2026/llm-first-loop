---
method_id: scope-repo-search-to-live-tree-exclude-snapshot-copies-2ecfd8aae869
name: scope-repo-search-to-live-tree-exclude-snapshot-copies
description: 在含整树快照副本（如 .releases/<sha>/）的仓库中检索时，首批回执一旦显示命中被同一逻辑文件的快照前缀副本占据且列表截断，就应立即给后续检索加范围约束（排除快照目录）或直接按根目录路径读真源码，并核对 read 回执的 workspace_path_state=current_match。否则每次检索都被 N 份历史副本稀释，真源码可能被挤出截断窗口，导致重复枚举与无效换词。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d0721026-9d2f-493f-ad09-a5560e92b589:36:80e702f27893db0753b0
evidence_refs: learning:learn:fb70901f771e
created_at: 2026-10-13T04:26:06.595367+08:00
updated_at: 2026-10-13T04:26:06.595367+08:00
---
## Trigger
在含 .releases/、vendor/build 快照等整树副本的仓库做文件名/内容检索；首批命中大量共享同一快照前缀（如 .releases/<40位sha>/）且标注截断（显示前 20）；需要定位当前工作树真源码而非历史版本。

## Discriminator
首个检索回执当时已可见：全部命中共享 .releases/<sha>/ 前缀且列表被截断，说明语料存在整树快照复制，无范围约束的检索会被副本噪音淹没；同源内容检索中同时出现无前缀的根路径命中（如 tests/unit/...、webui/src/...），证明工作树在根目录、真源码存在且可直接按根路径读取。

## Short path
- 第一次检索返回快照前缀重复且截断的命中 → 未知量：当前工作树中目标文件在哪
- 立即对后续检索加范围约束（排除 .releases/ 等快照目录），或用一次带内容过滤的检索确认根目录布局（无前缀命中即工作树位置）
- read_file 根目录真源码，核对回执 workspace_path_state=current_match
- 取得所需定义/路由/签名后停止，不再发无范围的全库检索

## Stop conditions
- 已读到 current_match 的真源码并取得用户目标所需事实
- 工作树中该文件不存在、唯一来源是快照副本——此时读快照但如实标注其为历史版本而非当前源码

## Verification
- read 回执 workspace_path_state 必须为 current_match 才可作为当前版本证据
- 对命中列表去快照前缀后复核，确认目标逻辑文件在活树中唯一
- 后续引用该文件路径时不得混入快照前缀副本

## Counterexamples
- 任务目标本身就是历史 release（如'审计某快照版本发布了什么'）——.releases/ 路径是检索目标而非噪音，排除会直接出错
- 工作树已删除/改名该文件，仅快照含之——快照副本是唯一来源（但须标注非 current_match）
- 语料无整树副本结构（无 .releases/vendor 目录）——强加排除约束不缩小空间，反而可能漏掉合法命中
