---
method_id: cross-receipt-contradiction-pivot-when-search-returns-no-match-d7022c44200f
name: cross-receipt-contradiction-pivot-when-search-returns-no-match
description: 专用搜索工具（文件名/内容检索）对某词返回『无匹配』，而同任务早前另一工具回执已明确列出匹配该词的工件（如失败检索附带的『最近文档参考引导』清单点名了含该词的标题/路径）时，负结果反映的是该工具语料/根目录/模式错位，不是目标不存在。此时不要在同一工具内换措辞重试，立即换机制对已知语料做一次范围受限的定点检索（如 scoped grep/rg）即可命中。
aliases: 搜索说没有但参考清单里明明列了, 查无此文件但别的回执提到过, 空结果和已知文档打架怎么判, 工具搜不到时先对照手里清单, no-match 不可信换机制一次定生死
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:8cdc10d0-aa2b-4b38-b050-e87862e63307:74:2e72724197c758527fb1
evidence_refs: learning:learn:b16d95254081
created_at: 2026-10-27T22:19:35.883315+08:00
updated_at: 2026-10-27T22:19:35.883315+08:00
---
## Trigger
需要在仓库/文档集中定位一件应存在的工件（文档、记录、文件），专用搜索工具刚返回『无匹配』，且本任务早前回执中已出现与查询词字面匹配的确切标题、路径或样例。

## Discriminator
跨工具回执矛盾是否成立：把 no-match 与早前回执列出的清单对照，若清单字面包含查询词（如引导清单点名某排期文档含 P1-5、某报告名含『安全』），而搜索工具对同词返回无匹配——矛盾一旦成立，负结果即被证伪，唯一剩余解释是该工具没看对地方。

## Short path
- 检索失败回执若附带参考引导/相关清单，先从清单提取与目标同词的确切标题或路径
- 首次搜索工具 no-match 后立即与该清单对照：词面匹配即判定语料错位，弃用该工具
- 换机制一次：对已知语料根（如 docs/）跑 scoped grep 精确 token，定点命中
- 命中后停止发现，直接读取命中的权威工件；不再回搜索工具复验

## Stop conditions
- scoped grep 命中且路径/标题与早前回执清单能对上，进入读取/使用
- 换机制一次仍无匹配 → 负结果转为可信，回到扩查询或换数据源分支，不再怀疑该工具

## Verification
- 命中文件的路径或标题与早前回执列举项一致（同一文档/同一命名族）
- 若对不上，说明矛盾另有解释（版本/镜像差异），退回存在性判断而非继续轮换工具

## Counterexamples
- 没有任何其他回执断言匹配物存在（首次检索、无引导清单/目录样例）时，no-match 是有效负证据，应扩查询措辞或换来源，而非预设工具坏了
- 工具回执自带 partial coverage 标记的负结果，适用『部分覆盖不得下不存在结论』的闸门，不是本卡的语料错位情形
- 目标工件本就在该工具语料之外（远端平台、另一 store），换 shell grep 无意义，应换数据源
