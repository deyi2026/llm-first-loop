---
method_id: live-copy-first-when-search-hits-snapshot-forests-cfbfa757fb77
name: live-copy-first-when-search-hits-snapshot-forests
description: 在含版本快照森林（.releases/<hash>/、.worktrees/）与 vendored venv（site-packages 复制）的仓库里，宽文件/内容搜索的回执会被同相对路径的复制副本刷屏。把首次回执当地图：反复出现的相对路径后缀就是真实模块布局，无前缀（仓库根相对）副本即 live 源码，config 里 *_dir 默认值即运行时数据目录。沿这两条已显式 provenance 边直读 live 路径并在后续搜索中排除快照/venv 前缀，替代换词重复宽搜索与 home 目录/find 探测。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:163:a1f0d52bdf882ac17818
evidence_refs: learning:learn:40c4b3fe8128
created_at: 2026-10-17T23:41:20.300824+08:00
updated_at: 2026-10-17T23:41:20.300824+08:00
---
## Trigger
宽泛文件名/内容搜索的回执被 .releases/<hash>/、.worktrees/、.venv*/lib/.../site-packages 等前缀下的同一路径复制刷屏，而任务需要理解/修改/统计当前运行版本的实现或数据

## Discriminator
首次回执中命中聚在相同相对后缀（如 src/llm_loop/methods/store.py）、仅前缀不同——这本身即证明：仓库存在版本复制森林，live 副本=无前缀路径；一次 grep config 的 *_dir 默认值（./data/methods、./methods）即给出运行时数据位置。两者在最初一两条回执内已可见，无需再用变体词搜索

## Short path
- 首次宽搜索回执到手后先读路径结构：命中重复同一相对后缀仅前缀不同 → 判定为快照/venv 复制森林，锁定 live 无前缀路径为唯一待读目标
- 直接 ls/读无前缀 live 路径（如 src/llm_loop/methods/）并 grep 其关键函数，替代第二次换词宽搜索
- 对运行时数据位置，一次 grep config 的 *_dir 默认值，同时拿到 runtime 数据目录与 seed 目录两条权威边，不再探测 ~/.home 或 find -name METHOD.md
- 后续搜索与统计一律排除 .releases/.worktrees/.venv 前缀（或只取无前缀条目），从 config 声明的 data 目录直接统计台账（状态计数、verdict/usage 分布）
- live 实现逻辑与数据实测分布都已到手即停止发现，进入方案设计

## Stop conditions
- live 无前缀源码与 config 声明的数据目录均已读取，关键事实（实现逻辑 + 数据分布）已实测
- 回执中已出现唯一无前缀命中时，不再枚举快照副本

## Verification
- 确认最终引用的文件路径不含 .releases/、.worktrees/、.venv 前缀，且与 config 声明的目录一致
- 关键量化结论（如 qualification 证据弱、usage=0）来自 live 数据目录台账统计而非快照副本

## Counterexamples
- 任务本身是比较版本差异（哪个 release 引入/改变某行为）：快照森林就是目标，必须跨副本枚举而非只读 live
- 目标 API 只存在于旧快照或 venv 副本、live 已删除：直读 live 会漏，需沿副本回溯
- 仓库无快照/venv 结构，首次搜索命中的就是 live 文件：直接读即可，路径去重规则无增益
