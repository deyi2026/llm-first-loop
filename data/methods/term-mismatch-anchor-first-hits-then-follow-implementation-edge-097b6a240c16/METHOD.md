---
method_id: term-mismatch-anchor-first-hits-then-follow-implementation-edge-097b6a240c16
name: term-mismatch-anchor-first-hits-then-follow-implementation-edge
description: 代码库概念问答（'X 是否与 Y 统一/结合'类）中，用户用词与仓库词汇不一致时，第一次概念搜索的命中集本身就是『术语映射表+实现指针』：它框定了目标概念的角色并点名 owning modules，同时外来词与目标概念零共现。此时应沿命中集点名的实现边读结构→定点读机制；外来词直译解释最多花一次内容探测，探测的空/噪声回执恰好是答案 caveat 的证据。禁止在已有实现边时另开 docs/文件名模式/猜测符号等宽搜索分支，禁止搜索仅由散文注释推断（而非实际看见）的符号名。本卡继承 provenance-following 核心，新增的判别子是『术语零共现+有界直译探测』。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6011132d-5da7-46ed-9be9-40d1379ec22d:880:5592a507ed05d337bfea
evidence_refs: learning:learn:bc939f4ec1ac
created_at: 2026-10-11T14:18:19.830433+08:00
updated_at: 2026-10-11T14:18:19.830433+08:00
---
## Trigger
用户提出'X 与 Y 是否统一/结合/集成'类概念问答，X 或 Y 使用仓库外词汇；第一次概念内容搜索已返回结构化命中集。

## Discriminator
命中集同时满足：①已点名目标概念的权威实现面（配置/变更记录框定其角色，eval/调用点给出 owning module 路径）；②外来词与目标概念在任何命中中共现次数为零。这两点当时即把答案空间收敛到点名模块内，后续任何宽搜索类调用先验上几乎必然无信息。

## Short path
- 第一次概念内容搜索：把命中集读作术语映射+实现指针（该概念在本仓库是什么、由哪些模块拥有）。
- 对外来词做至多一次内容探测以判定直译分支是否真实存在；噪声/零共现结果直接写入答案的 caveat。
- 沿命中集点名的 owning modules 读代码结构面（类/函数/注释），定位能回答未知量的机制入口。
- 对具体机制定点 grep/read（入口接口、绑定/会话逻辑、预算或滚动等），不再引入新的搜索类。
- 组合答案：机制结论+外来词在本仓库的实际所指，逐条引用已暴露的 file:line；停止。

## Stop conditions
- 实现面已确认集成机制（入口接口与绑定/预算逻辑可见）且问题是概念问答而非穷举审计。
- 问题的每个子句未知量都已有权威回执，剩余搜索类（docs/文件名/猜符号）不再可能改变答案。

## Verification
- 答案中每个机制断言可指回轨迹中已暴露的 file:line 或结构输出，无凭记忆断言。
- '统一/结合'方向断言须有代码证据（同一入口接口、绑定存储、复用路径），不能仅靠配置注释。
- 外来词 caveat 与探测回执一致（如实列出命中的无关含义，如 HTTP 中间件/Django 等）。

## Counterexamples
- 第一轮搜索命中分散、无明确 owning module：此时需要 broad discovery，本方法不适用。
- 外来词与目标概念在命中集中真实共现（存在真实桥接组件）：直译分支是主路径，须沿它深读，而非一次探测了事。
- 任务本身是穷举审计（'列出所有 X 触点/引用'）：全量枚举是需求，宽搜索不算摩擦。
- 已知代码与设计文档漂移、或用户问的是设计意图而非实现：docs 优先是正确路径。
