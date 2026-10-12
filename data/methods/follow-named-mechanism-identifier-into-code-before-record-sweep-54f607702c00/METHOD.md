---
method_id: follow-named-mechanism-identifier-into-code-before-record-sweep-54f607702c00
name: follow-named-mechanism-identifier-into-code-before-record-sweep
description: 当状态/配置回执自带机制自标识（schema 字符串、组件名、action 前缀）时，先沿该标识在权威实现（本地代码）中定位机制定义，再由定义反推需要核验的本地事实；记忆记录与文档枚举降级为该标识边失效后的分支手段。每步只解决一个未知量：机制在哪定义→它要求什么前置→这些前置在本机的实际取值。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:e8e83cd1-6d33-4a6b-b29b-56131638f5d7:741:22ddc6fbf0f859b40f52
evidence_refs: learning:learn:c515449eebfd
created_at: 2026-09-19T01:35:18.477104+00:00
updated_at: 2026-09-19T01:35:18.477104+00:00
---
## Trigger
目标是弄清或操作某个运行机制（发布/重启/状态写入），且手头回执已显式给出该机制的自标识字段，而尚未锁定任何具体未知量

## Discriminator
进入任何记录/文档搜索之前，第一步的状态回执已含 schema=managed-service-deployment/v1 及 service-control 回执字段（svc-… action_id、matches_desired_generation、reasons）。这个自标识字符串可在本地代码中被精确 content-search 命中，把'机制在哪定义'从全部记忆记录+全部文档缩成一次精确查找；当时未利用，转而做了两条记录宽搜（10 条候选、无直接命中）和一次文档宽搜（未命中）。

## Short path
- 读状态回执，解决未知量：当前 generation/git_head/roots 与控制机制身份——此时已免费拿到 schema 自标识
- 用该 schema 字符串对代码做 content search 定位机制模块，读其校验逻辑与 CLI 定义；未知量：publish 的机械前置与接口（HEAD 须等于目标、工作树干净、CAS expected-generation）
- 由已读前置条件派生只读预检，每次只查一个未知量：目标 commit 与 main 的关系（双 hash 同 commit message 用 patch-id 判定）、占用 main 分支的 worktree、主 checkout 是否 dirty
- 写出操作步骤与失败分支（CAS 代次冲突=重读重排而非改数重试，语义来自已读代码）；所有未知量已被权威实现覆盖，停止

## Stop conditions
- 机制定义（校验规则+CLI 接口）已从其实现模块读出，且能逐条解释状态回执中的相关字段
- 定义要求的每个本地前置都已用一次只读检查核实，操作步骤与失败分支可写出

## Verification
- 标识字符串搜索命中实现模块而非同名巧合：读到的校验逻辑应能解释回执中每个相关字段
- 每条操作前置能回指到已读代码条款（HEAD==目标、tracked 干净、CAS 代次），不凭记忆记录转述

## Counterexamples
- 机制不在本地代码中（外部 CLI/远端控制面）：schema 字符串搜不到实现，此时记录/文档搜索才是正确第一跳，本方法不适用
- 未知量本身就是历史行为模式（'以前这类重启怎么失败'）：记忆记录搜索就是针对性定向查询，不属于宽枚举摩擦
- 回执无任何自标识字段（无 schema/组件名/前缀）：没有可沿的 provenance 边，应先做宽发现建立标识，再套用本方法
