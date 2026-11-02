---
method_id: first-receipt-mirror-dirs-scope-all-discovery-to-live-tree-049b18b44da0
name: first-receipt-mirror-dirs-scope-all-discovery-to-live-tree
description: 仓库带全树镜像/发布快照目录（.releases/<sha>/ 等）时，首次检索回执本身已揭示镜像结构：同一相对路径多份副本 + 唯一现行实例。此后所有定位、内容检索、测试发现与运行验证都应绑定 live 前缀或显式排除镜像目录，否则每轮检索被陈旧副本占据并触发截断（本集 9 命中 8 旧、20 命中约 16 旧、内容检索 30/34 条截断），live 命中有被挤出、误读旧代码为真的风险。用首份回执的结构把『全库含镜像』缩成『live 树定向』。
aliases: 搜索被旧版本快照刷屏, 命中一堆发布拷贝分不清哪个是现行代码, 怎么排除归档镜像目录再检索, 同一路径多份副本哪份才是真值, 读代码读到历史快照了
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:fb85cea0-beb4-424d-b482-2819180ee46f:535:e87ecab8290961f382cb
evidence_refs: learning:learn:6fd135c664c3
created_at: 2026-10-31T15:37:35.548315+08:00
updated_at: 2026-10-31T15:37:35.548315+08:00
---
## Trigger
在含全树镜像/发布快照目录（如 .releases/<commit>/、归档快照）的仓库里定位或修改代码：首次文件名/内容检索回执显示同一相对路径在镜像前缀下出现多份副本、库根仅一份现行实例，且之后还需多轮检索找实现、语义与测试。

## Discriminator
首份检索回执的结构（当轮可见）：命中按统一镜像前缀（.releases/<sha>/）成组重复，且仅一条无前缀的 live 路径（本集 9 命中 8 旧 1 新）。该事实已足以判定哪棵树是真值；继续无范围检索只会让陈旧副本挤占截断列表，live 命中可能被截掉。

## Short path
- 读首份检索回执的结构而非只看内容：命中是否带统一镜像前缀成组、是否存在唯一 live 实例 → 一次解决『哪棵树是真值』
- 后续定位与内容检索一律绑定 live 前缀（src/、tests/）或显式排除镜像目录，逐个解决『实现位置 → 契约语义 → 测试面』
- 直读 live 文件的契约 docstring 与目标函数段，不再全库宽搜
- 运行验证（探针、测试、类型检查）同样只指向 live 树（如 PYTHONPATH=src），防止 import/执行到镜像副本
- 若 live 前缀下检索 miss，把该 miss 当作定向扩围信号（改名/已删），而不是默认回退全库扫

## Stop conditions
- live 树内已取得实现、契约语义与测试面，且探针/测试回执与所读代码一致
- 确认任务对象是历史版本/演进对比（镜像即目标）时停止套用

## Verification
- 复查每次后续检索回执：不再出现镜像前缀命中（或已显式过滤）
- 最终读取与修改的路径不含镜像前缀；探针解析到的模块文件路径指向 live 树
- 对照 git status/最近提交确认所改文件不在镜像目录内

## Counterexamples
- 首次检索命中全部为现行文件（仓库无镜像目录）→ 收窄无收益，正常检索即可
- 任务要求版本考古（『这个函数几个版本前长什么样』）→ .releases/ 副本正是目标，收窄到 live 树会答错
- 无法从回执判定权威树（镜像目录才是部署源、live 树是生成物）→ 先解决权威性判定，再谈权窄
- 目标文件仅存在于镜像中（live 树已删/改名）→ live 前缀 miss 本身是转向信号，不应继续强行收窄
