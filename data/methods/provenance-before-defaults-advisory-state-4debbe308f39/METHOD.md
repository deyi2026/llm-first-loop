---
method_id: provenance-before-defaults-advisory-state-4debbe308f39
name: provenance-before-defaults-advisory-state
description: 当用户对进行中的工作区提出开放式建议类问题（“你的建议是？”）时，从已记录的 provenance/evidence 索引定向，而不是用假设的默认值（默认 workdir、默认 origin 远端、目录清点式侦察）：用索引中最近一条 verified-current 的 artifact 引用确定路径和权威状态文档；显式查询真实远端/分支拓扑后再做 ahead-behind 比较；只验证会改变建议的关键主张。可避免默认路径失败、清点式绕行和以旧镜像为基准的分叉计算。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:591:3724d9fce7d990da6056
evidence_refs: learning:learn:c9d01de076be
created_at: 2026-09-18T00:28:00.719560+00:00
updated_at: 2026-09-18T00:28:00.719560+00:00
---
## Trigger
用户对既有工作区提出开放式“下一步/你的建议”类问题，且存在已记录的 evidence/provenance 索引，同时状态可能散布在多个来源（结果文档、冻结回执、git 远端/分支）。

## Discriminator
evidence 索引中已列出带绝对路径和 freshness 元数据的近期引用——例如指向 RESULT/状态文档且 freshness=verified_current 的 edit_file 引用，加上 goal update/checkpoint 引用。这一事实把“当前状态在哪/用什么路径/先读什么”从清点问题收缩为一个具名 artifact，并提示环境拓扑（真实远端、cwd）应当查询而非假设。

## Short path
- 先读 evidence/provenance 索引：取最近一条 verified-current artifact 引用及其绝对路径作为工作位置，不经猜测默认值即解决 cwd 与状态文档两个未知量。
- 读该状态文档：列出建议所依赖的主张中哪些已被验证（冻结回执/提交哈希）、哪些仍开放。
- 显式解析拓扑（git remote -v / branch -vv）确定权威上游后，再做任何 ahead/behind 比较；不沿用惯例默认远端。
- 只执行建议真正依赖的定向比较（落后提交内容、与本地改动的重叠面），命令用执行器安全的 POSIX 语法。
- 建议的每个事实支柱都对应本回合内的工具输出；全部落实即停止，不再做额外 ls/ps 清点。

## Stop conditions
- 建议的全部事实支柱均可追溯到回合内工具输出（回执哈希、真实远端分叉数、重叠文件集、脏文件归属）。
- 状态文档加显式拓扑已回答所有开放未知量；继续侦察不会改变建议内容。

## Verification
- 将最终答案中的引用逐一对照工具输出：冻结哈希出现在权威远端比较的日志中，ahead/behind 数字来自真实远端而非旧镜像，重叠文件列表与 diff 输出一致。
- 确认没有任何主张隐性依赖未解析的默认值（workdir 路径、远端名称）。

## Counterexamples
- 全新任务且无（或过期）已记录 evidence：没有可沿的 provenance，宽发现（列目录、搜索、探测）才是正确首步。
- 索引中最新 artifact 引用只是部分覆盖的草稿编辑（coverage partial、freshness unknown），不是状态文档：先读它并不能界定未知量。
- 问题指向从未被记录的运行时现象（活跃进程、崩溃）：ps/ls 式侦察是必要取证路径而非绕路。
- 单一远端、路径已知的干净仓库：显式拓扑解析是多余开销，应直接进入比较。
