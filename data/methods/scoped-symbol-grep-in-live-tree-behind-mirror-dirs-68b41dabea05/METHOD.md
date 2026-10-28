---
method_id: scoped-symbol-grep-in-live-tree-behind-mirror-dirs-68b41dabea05
name: scoped-symbol-grep-in-live-tree-behind-mirror-dirs
description: 在含快照/镜像目录（.releases/<hash>/、backup、vendor 等）的仓库里定位某模块的现行位置时，若按概念名猜路径的 ls 落空，不要升级为全局文件名搜索，回执会先被镜像副本刷屏截断且给不出活树路径。正确下一跳：取一个最独特的符号/事件名，对已证实的活跃源码树根做 scoped 内容 grep，一步拿到权威现行文件再直接读取；仅当活树零命中才扩大到全局搜索，并把镜像目录命中视为陈旧副本。本集 search_files 20 条截断命中全在 .releases/，随后一次 src/ 内符号 grep 即定位。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:1536:bb321427fff6b7c856a6
evidence_refs: learning:learn:1d46a4152710
created_at: 2026-10-15T09:11:11.219447+08:00
updated_at: 2026-10-15T09:11:11.219447+08:00
---
## Trigger
仓库含快照/镜像目录（.releases/<内容哈希>/、backup、vendor 等）且需要定位现有模块/服务的现行位置；典型前兆：按概念名猜的路径 ls/读文件落空。

## Discriminator
当时已知两条事实：1) 此前对活跃源码树根（src/…）的 grep 已能返回精确 文件:行 命中，活树根已证实存在且可搜；2) 手头已有该模块的独特符号/事件名（可从设计文档引用或既有 grep 回执取得）。二者齐备即可把『全仓文件名枚举』缩成『活树内单符号 grep』。

## Short path
- 按显式章节号/索引读权威设计文档与已知包结构（沿用本集良好实践，不凭印象）。
- 期望路径落空时，从已读材料中选一个该模块最独特的符号/事件名。
- 对活跃源码树根执行 scoped 内容 grep（限定 --include 等文件类型），一步取得现行文件路径。
- 直接读取该活树文件，核对其与设计文档/规则引用一致后停止发现。
- 仅当活树 grep 零命中才扩大到全局文件名搜索；回执中 .releases/ 哈希目录命中一律视为陈旧镜像而非答案。

## Stop conditions
- 活树 grep 已给出唯一现行路径，且文件内容与上游文档引用的模块职责一致。
- 定位所需事实已从活树文件取得，无继续枚举候选的必要。

## Verification
- 命中路径位于活跃源码树根内，而非 .releases/ 等镜像目录。
- 文件内符号/事件名与上游文档引用一致（可用一次 grep 复核）。

## Counterexamples
- 只知文件用途、拿不出任何独特符号名时，全局文件名/目录遍历仍是合理起点。
- 仓库不存在镜像/快照目录时，全局文件名搜索本就干净高效，无需先做 scoped grep。
- 目标可能位于源码树之外（scripts/、生成代码、配置仓库）时，应扩大搜索 scope 而非固守 src/。
