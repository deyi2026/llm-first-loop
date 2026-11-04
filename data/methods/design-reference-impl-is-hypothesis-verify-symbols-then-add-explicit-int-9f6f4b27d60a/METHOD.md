---
method_id: design-reference-impl-is-hypothesis-verify-symbols-then-add-explicit-int-9f6f4b27d60a
name: design-reference-impl-is-hypothesis-verify-symbols-then-add-explicit-interface
description: 执行设计文档任务表中的接线类任务时，把任务表（what）当契约、参考实现（how）只当假设：先对参考实现点名的每个符号（访问器/import/方法）在 src 定义面做一次存在性与语义核验——import 指向不存在的访问器、docstring 与实现体语义漂移、数据源返回混合语义集合（如在飞+重启前孤儿）都会在这一步暴露。符号缺失→在真实装配点补注入链，不照抄文档形状；旧接口 docstring 漂移→新增显式语义的窄接口（如按运行态字段过滤）并登记漂移，不动旧调用方；混合语义源→拒绝接入纯语义视图，宁可少报不可伪报。前置信号：该文档已有勘误表或前轮错误编号史。
aliases: 设计稿参考实现不能照抄, 文档里的import跑不起来, docstring和实现不一致, 接线前先核符号存在, 旧接口语义漂移加新接口别改旧的, 数据源混了孤儿别接视图
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:73172f2a-c1f6-4868-9611-d4af1d463c48:1108:afdde7246e495e55f595
evidence_refs: learning:learn:1b4d14e3daaf
created_at: 2026-11-03T20:09:44.160042+08:00
updated_at: 2026-11-03T20:09:44.160042+08:00
---
## Trigger
按设计文档任务表逐项执行接线/实现任务（常为续轮『下一步』），文档同时给出参考实现或伪代码，且该文档有勘误史、或参考实现从未在真实代码上运行过

## Discriminator
文档自身带勘误表/前轮错误编号、且参考实现标注为『参考』而非已落地代码——这两个当时可见事实把『照参考实现写』缩成『逐符号定义面核验后再接线』

## Short path
- 读任务表确定下一任务的 what 与验收，用 git status delta 定位上一轮在飞文件，不做仓库级宽搜索
- 对参考实现点名的每个符号做 scoped 检索+定义面直读：核验存在性、docstring 与实现体是否一致、返回集合的语义是否纯净
- 按核验结果分支：符号缺失→在真实装配点（engine 构造/上下文注入）补依赖链；docstring 漂移→新增显式过滤的窄接口并登记，不改旧调用方；数据源混合语义→换纯在飞口径的源
- 每分支配一条测试，加零写守卫与真实装配注入断言，绿后停止并登记新发现的文档错误

## Stop conditions
- 任务表点名的每个符号均已在定义面证实存在，或已被显式替代并登记
- 视图数据源语义与视图声称语义一一对应（『在飞』就是纯在飞）
- 发现的漂移均已编号登记，scoped 测试全绿

## Verification
- grep 符号在 src 的定义处并读实现体，逐条对照 docstring 与调用方假设
- 测试断言新接口确实按运行态过滤、视图零写（调用前后 audit 目录 mtime+size 不变）
- 断言真实装配点完成注入（如 ctx 字段 is engine 对应组件）

## Counterexamples
- 参考实现已在先前 PR 逐字落地且测试绿：符号已验证，直接复用不再核验
- 全新代码无既有调用方：直接在原地修正漂移接口比加并行接口更省
- 视图语义本就要求混合集合（『谁可能还在跑』含重启前孤儿）：混合语义源是正确选择，不应拒绝
- 用户最新指令与任务表冲突：以用户指令为准，任务表不是最高契约
