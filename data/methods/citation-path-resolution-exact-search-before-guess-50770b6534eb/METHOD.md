---
method_id: citation-path-resolution-exact-search-before-guess-50770b6534eb
name: citation-path-resolution-exact-search-before-guess
description: 审计外部评审/文档引用的代码事实时按引用形态分流取证：带完整目录路径的引用直接读原文区间；只给裸文件名+行号的引用先用精确文件名（或引用行内容中的特征符号）检索定位权威路径，再读区间核对。同批兄弟引用所在目录不能外推到本文件；猜测路径的失败回执无法区分'文件不存在'与'猜错目录'，等于白耗一次调用。核对结论分'证实/勘误'两类记录，路径勘误显式写回修订说明。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:130:40dc4fbe719504631324
evidence_refs: learning:learn:a722d5c86c7b
created_at: 2026-10-01T23:26:03.627066+08:00
updated_at: 2026-10-01T23:26:03.627066+08:00
---
## Trigger
收到引用多条代码事实的评审/文档、需要先取证再决定如何修订，且其中部分引用只有文件名（或符号名）+行号而无目录成分。

## Discriminator
进入首次读取前即可观察：该引用不含目录（如仅 `tool_reachability.py:95-133`），工作区内没有任何先验证据把该文件放在猜测的目录下——猜测目录只是把'文件在哪'这一个未知量换成'对目录的枚举'；而精确文件名/符号检索一次即可解析出唯一路径（本集：search_files 命中 llm_loop/core/loop/engine_services/tool_reachability.py，且同集对 _transport_attempt_scope、_REQUEST_PREAMBLE、_trace_payload_fingerprint 的内容检索均一次命中、零失败）。

## Short path
- 解析每条引用并二分：带完整路径 → 直接读引用区间；只有裸文件名/符号 → search_files 按精确文件名或特征符号定位权威路径
- 读取定位后的区间，逐条与评审声明比对，产出'证实/证伪/路径勘误'三类结论
- 仅当检索也解析不到时才升级为目录级/内容级宽搜索
- 全部引用核对完毕后再修订文档，不提前写实现；勘误写进修订说明

## Stop conditions
- 每条被采纳的修订都能指回一次成功读取的当前源码区间，未知量（文件在哪、声明是否属实）已闭合
- 检索返回唯一路径且引用区间已读取比对完成

## Verification
- 对每条被采纳的修订，回查其对应的成功读取回执（正确路径+行号）而非评审原文
- 路径勘误显式成文（如 tool_reachability.py 实际在 core/loop/engine_services/、execute_command.py 在 tools/builtin/），不默默用新路径替换

## Counterexamples
- 引用已含完整目录路径且快照回执显示 workspace_path_state=current_match：直接读，再检索是浪费
- 验证目标本身就是'该路径/该版本是否存在'：read_file 失败本身就是证据（证明引用过期或文件被移动），不是需要检索挽救的错误
- 文件名过于常见会命中大量结果：改用引用行内容中的独特符号做内容检索，而不是按文件名枚举候选
- 核对对象是历史 revision 而非当前工作区：应在指定版本上读取，按文件名在当前树检索会引入版本错位
