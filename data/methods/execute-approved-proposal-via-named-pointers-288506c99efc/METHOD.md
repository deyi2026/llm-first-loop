---
method_id: execute-approved-proposal-via-named-pointers-288506c99efc
name: execute-approved-proposal-via-named-pointers
description: 任务以"某带 ID 的提案已批准、请核实后继续执行"开场时，按 ID 首次检索到的提案记录本身就是变更面的权威清单：缺陷证据、根因 file:line 指针、方案都在其中。应直接读取这些命名位置核实代码现状，再用核心符号的内容搜索闭合改动面（全部注入/消费/测试点），然后实施。反模式：对提案已命名的文件再做文件名搜索（本集对 registry.py、wait.py 各多搜一次）、对已读文件再发存在性查询、用 event_stream 回查本会话 action trace 充当新信息、按文件名模式搜测试目录命中大量同名无关 registry。只有命名指针断裂或符号枚举超出提案清单时才扩大发现面。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:920:1c84f24890b8b5ca6452
evidence_refs: learning:learn:5d9415de5c65
created_at: 2026-10-12T09:08:57.680167+08:00
updated_at: 2026-10-12T09:08:57.680167+08:00
---
## Trigger
开场是人工回执/审批通知：某带 ID 的变更提案已批准（状态 executing），要求核实状态后继续执行修复；目标是对已知缺陷实施一次代码变更。

## Discriminator
首条 search_records 回执中的提案全文在当时已给出根因的文件指针（wait.py；registry.py:1572 copy_context 快照边界）与修复方案——"改哪些文件/位置"这一未知量已被权威记录收窄，后续对已命名文件的文件名搜索（各仅命中 1 条）与存在性查询都是对已闭合空间的重复枚举。

## Short path
- search_records(kind=evolution, query=ID) 取完整提案：解决"批准了什么、根因在哪、方案是什么"
- 直接 read_file 提案命名的根因位置（wait.py 全文、registry.py 1572 邻域）：核实当前代码与提案分析是否一致
- 对核心符号（child_wait_budget_used）做内容搜索，枚举全部注入/消费/测试点：闭合改动面是否超出提案清单
- read_file 注入点上下文（runner.py ~1366）与既有专项测试：确定注入模式与测试基建
- 实施共享可变载体改造；新增经真实派发边界（registry.execute/copy_context）的回归测试并定向跑
- 发布并排程 live 复验，以机械回执确认后停止；未完成项如实声明

## Stop conditions
- 提案命名指针与当前代码快照一致、改动面经符号枚举闭合 → 停止发现，进入实施
- 命名指针断裂（文件不存在/行号漂移/workspace_path_state≠current_match）→ 此时才转入文件名/内容/结构发现式搜索
- 回归测试在真实派发边界复现缺陷（旧实现必挂）且定向套件通过 → 进入发布与 live 复验阶段

## Verification
- 每个被修改文件都能归因到"提案命名 ∪ 符号引用枚举"的并集，不存在凭文件名猜测引入的额外文件
- 新增回归测试确实穿越缺陷所在的派发边界（经 registry.execute 而非直接调用工具），并验证其对旧实现必挂
- 发布/live 复验以回执为准（publish 绑定 commit、重启受理、事件日志数值 1s→2s→7s），未完成步骤如实声明而非宣称完成

## Counterexamples
- 提案记录只有标题/状态、无根因 file:line（人工只批准方向）："改哪里"未被收窄，仍需自主定位，本方法不适用
- 命名位置与当前代码不符（文件已重构、行号漂移、snapshot 非 current_match）：指针断裂，须先转发现式搜索再实施
- 开放性调查任务（无 ID、无批准记录）：不存在提案这条 provenance edge，套用会错误跳过必要的广搜
- 符号枚举发现提案未列出的消费点（如 contextvar 存在提案外第 5 处引用）：应以枚举为准扩大改动面，不得被提案清单锚定而漏改
