---
method_id: first-party-scope-discovery-when-vendor-trees-match-the-keyword-73e828d729aa
name: first-party-scope-discovery-when-vendor-trees-match-the-keyword
description: 在含多个 .venv/site-packages 的仓库里核对『本系统如何实现某命名机制』时，先用问题/本地记录里已有的首属标识符把文件名/grep 检索限定在第一方源码子树（如 src/）：site-packages 中的同名文件（langchain/deepagents/openai 的 subagent 模块）是其他系统对同一概念的实现，主题高度相似但回答的是错误问题。命中面收敛后先完整读公开接口定义文件（工具类 docstring+description 即最密的机制规格），超大 runner 内部只按当前未知量做锚点 grep。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:1f7d0adc-baca-4f64-a8b0-4a355d8a5973:0:57f0c8493e428574cdef
evidence_refs: learning:learn:5d08c01b4df1
created_at: 2026-10-23T05:25:05.980668+08:00
updated_at: 2026-10-23T05:25:05.980668+08:00
---
## Trigger
用户问题或本地记录已点名某机制的属主系统与公开接口标识（如 spawn 回执/steer/结算查询），需在本仓库核对该机制实现；而仓库根枚举显示存在 evals/*/.venv 等依赖树（或 .releases 镜像），无作用域的文件名检索会被第三方同名实现刷屏。

## Discriminator
检索回执的前几十条命中是否全部位于 site-packages/.venv 路径、且文件主题与目标机制同名同义——这是『别的框架的实现』信号而非目标缺失；同时根枚举已显示有界的第一方源码子树（src/），且问题关键字（子agent/spawn）在语义上归第一方代码所有：正确的下一跳是 find src 而不是继续换关键字全仓扫。

## Short path
- 取外部论断与本地记录（可并行），从问题/记录提取机制的首属标识符（工具名/通道名）。
- 目录结构未知时先一次有界 ls 定位源码子树；随后 find <src子树> -iname '*<标识符>*'，一次拿到全部第一方实现文件（本集 25 行输出即覆盖 8 个实现文件）。
- 先完整读公开接口定义文件：工具类的模块 docstring 与 description 字段本身就编码了机制规格（非阻塞、白名单程序级强制、深度上限、能力 fail-fast、grant 语义），与外部论断的分类逐项对得上。
- 超大内部文件（3352 行 runner）只按当前未知量做锚点 grep（MAX_DEPTH/lease/reaper）加定点读，不整读。
- 把外部论断逐机制映射到已核验的本地事实；对外部关于第三方框架的描述显式标注未独立核验，然后停止。

## Stop conditions
- 第一方源码树内已无未读的同名实现文件，且对比所需的每个机制断言都有 src/ 路径级证据。
- 外部文章的机制分类每项都有本地对应实现或显式『无对应』结论，未核验边界已声明。

## Verification
- 最终答案引用的每条本地行为断言都落到第一方路径（src/llm_loop/...），无任何一条证据源自 site-packages 文件。
- scoped find 的结果集覆盖答案中引用的全部实现文件（工具面 + delivery/topology + runner）。

## Counterexamples
- 目标本身就是第三方依赖的实现（问『langchain/deepagents 怎么做 subagent』）：site-packages 命中即目标，排除它们就错了。
- 仓库无 vendored 依赖树且关键字唯一：一次全仓检索已是有界动作，再加排除步骤纯属开销。
- 机制没有公开接口名（内部重构、未注册能力）：标识符检索会落空，应转能力目录/registry 枚举，而不是继续换关键字扫。
