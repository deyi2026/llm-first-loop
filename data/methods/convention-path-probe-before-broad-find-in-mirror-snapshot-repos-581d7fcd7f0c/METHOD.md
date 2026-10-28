---
method_id: convention-path-probe-before-broad-find-in-mirror-snapshot-repos-581d7fcd7f0c
name: convention-path-probe-before-broad-find-in-mirror-snapshot-repos
description: 在存在快照镜像目录（.worktrees/、.releases/、vendored 拷贝会把全库文档复制多份）的仓库里定位一个已知文件名但路径未知的文档时：若本集早前输出已经展示该类文档的目录约定（如 docs/），且搜索回执已出现镜像重复命中，则窄探测失败后应先探测约定路径或用排除镜像目录的受限发现，而不是全库 find。默认非镜像路径为权威版本；镜像副本可能是过期快照，误读既是成本也是正确性风险（本集 find 返回 141 条命中，其中约 140 条为镜像）。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:8432bab4-9ec8-4407-a69c-0cd2c90dce64:1154:e2860d7e502481e06b44
evidence_refs: learning:learn:eb6e423a4538
created_at: 2026-10-15T14:17:23.800356+08:00
updated_at: 2026-10-15T14:17:23.800356+08:00
---
## Trigger
已知文件名的文档/配置路径不确定；在某个猜测位置（如仓库根）的窄探测刚刚失败；且早前工具输出已建立该类工件的目录约定（例如 docs/ 下已成功 ls 过），或搜索/枚举回执已出现同一文件的多份快照镜像副本

## Discriminator
早前 ls/search 回执是否已同时给出两个事实：(a) 该类文档的规范目录约定（本集首个 ls docs/promotion/ 成功、search_files 首命中即 docs/ 下规范副本）；(b) 发现结果被 .worktrees/、.releases/ 等镜像目录污染（search_files 一次返回 1 规范 + 3 镜像）。二者俱在时，一次约定路径探测即可定位目标；全库 find 只会枚举大量过期副本并引入误读风险

## Short path
- 窄探测失败后先盘点已知量：确切文件名（可来自上游文档的关联/引用字段）、工件类别、已观察到的约定目录
- 探测约定路径（如 docs/<文件名>）；命中即只读该规范副本
- 未命中才做受限发现：find 时排除镜像目录（.worktrees/、.releases/、node_modules 等），或仅在约定目录内 find -name
- 从规范副本读取所需内容并在最终引用中标注规范路径
- 若确需读镜像副本，先核对其 commit/版本与规范基线一致

## Stop conditions
- 规范（非镜像）路径副本已定位并读出所需事实（如生命周期规则原文）
- 约定路径探测与受限发现均未命中，才升级为全库枚举

## Verification
- 确认最终读取路径不在任何镜像/快照目录内
- 引用该文档产出的统计或规则时，来源标注为规范路径而非镜像路径
- 若使用了镜像副本，diff 其与规范副本或核对基线 commit 后再采信

## Counterexamples
- 任务目标本身就是某个特定 release/worktree 快照的内容——镜像即目标，读规范路径反而取错对象
- 该类工件没有已观察到的目录约定，且失败的猜测位置已是唯一假设——此时受限/全库发现是合理下一步
- 单副本小仓库无镜像污染——约定探测仍更省一步，但全库 find 的噪音与误读风险基本消失，方法收益趋近于零
