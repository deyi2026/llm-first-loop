---
method_id: live-code-grounding-over-chat-archaeology-ca680180ad24
name: live-code-grounding-over-chat-archaeology
description: 回答『上一轮遗留问题是否已修/是否需重启/如何修』时，把当前代码与 git/进程事实当唯一真值：先沿 commit→改动文件的 provenance 边定位代码，再用『commit 时间戳 vs 运行中进程启动时间 + 实例化侧归属』得出重启结论；对上一轮对话原文只做有界检索——一旦回执暴露存储范围（如『当前会话 Evidence』）或事件流只含 action_trace（无正文），立即停止跨库换词考古，把用户措辞直接映射为当前源码可验证的谓词并给建议。
status: active
source_model: glm/glm-5.3
source_episode_refs: episode:35effbfe-0312-45d2-a1bd-0418c1706ecd:251:caa587d7c431ba473e05
evidence_refs: learning:learn:1f6bb0a0fbcb
created_at: 2026-10-18T21:21:06.836441+08:00
updated_at: 2026-10-18T21:38:25.528142+08:00
---
## Trigger
用户引用上一轮评审/拷问结论，询问某遗留问题是否已修复、是否需重启生效或要求修复建议，而上一轮对话文本不在当前上下文中（当前代码里甚至搜不到问题关键词）。

## Discriminator
检索回执本身暴露的存储事实：如『未找到匹配…的当前会话 Evidence』说明库是 session 级、event_stream 只返回 action_trace 的 tool_calls 说明流只记动作不记 assistant 正文——旧对话正文在可用库里结构性缺席；同时用户措辞（如『无 name 控件』『短稿』）可直接映射为当前源码可验证的谓词（label 回退逻辑、可比行阈值）。

## Short path
- 工作区路径假设失败时，用一条 pwd && git rev-parse --show-toplevel 锚定真实仓库，不逐个试记忆路径
- 从已命中的 HEAD commit 直接 git show --stat 取改动文件清单（commit→files 的 provenance 边），不做全库内容搜索
- grep 类/工具的实例化点确认执行体归属（主进程装配 vs 子进程），并列出所有运行中服务的启动时间与启动时 git head
- 取 commit 时间戳与各进程启动时间逐一比较 → 重启结论，引用实例化行号佐证
- 把每个遗留问题按用户措辞映射到当前代码符号（grep 函数/属性名 → read 对应行段），建议直接落在可引用的代码事实上
- 旧对话原文每库最多检索一次；首份回执显示 scope/格式不含正文即停止考古，显式声明『以代码现状为准』

## Stop conditions
- 重启问题在『commit 时间 > 所有相关进程启动时间 且 实例化侧已确认』时关闭
- 每条建议都有本会话读到的具体函数/行号支撑时关闭
- 对话考古在第一份暴露存储范围或流格式的回执后即停止，不再换词/换库重试

## Verification
- 最终答复中的每条代码断言都能回指本会话读到的函数与行号（如 _page_controls 只取 name 与 _publish_label_candidates 的 name→text 回退的不对称）
- 重启结论以表格逐一列出每个运行服务的 started_at、启动时 git head 与 commit 时间戳比对
- 若未取回上一轮原文，显式说明建议基于代码现状而非对原文的凭记忆复述

## Counterexamples
- 用户明确要求复述上一轮的结论/决策本身（目标事实就是那段话而非代码状态）——必须做跨会话检索或直接问用户，不能以代码代替
- 回执显示归档库确含跨会话记录（cross_session 可用）时，一次归档查询就是合法 provenance 边，应先查再读码
- 问题针对旧版本代码描述且相关符号已被重命名/删除——只读当前代码可能定位错路径，需先查该符号的 git 历史
