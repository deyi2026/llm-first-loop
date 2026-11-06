---
method_id: resolve-failing-node-from-run-logs-before-flake-repro-loops-94489c43e48c
name: resolve-failing-node-from-run-logs-before-flake-repro-loops
description: 抖动/间歇失败定性任务若任务书只给模块级关键词而非精确 test node ID，第一未知量不是『在哪个测试文件上开复现循环』，而是『历史权威记录里到底哪个 node 失败过』：先 grep CI/全量运行日志中的 FAILED 行，解析出精确 node ID 与失败详情，再据此启动隔离/批/全量的梯度复现。同名测试文件跨 suite 存在、且测试树关键词 grep 只命中 __pycache__ 编译缓存（还可能被 head 截断）时，按文件名选目标必有歧义——本集即在 phase5 上跑了一个 48.98s 用例并铺开 5 连后台循环后，才发现历史失败在 phase6，被迫终止重跑。
aliases: 抖动定性先翻失败日志再复现, 同名的测试文件不止一个, flake 复现先锁定精确用例, 只给模块关键词怎么找失败用例, grep 只中 pycache 别急着定文件
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a6989bff-e814-43eb-9f8a-a24f42790dd9:1367:6022eeb89b860892d30a
evidence_refs: learning:learn:290808847abb
created_at: 2026-11-06T09:25:57.666135+08:00
updated_at: 2026-11-06T09:25:57.666135+08:00
---
## Trigger
定性/修复间歇性失败（flake、抖动、负载相关超时）时，任务描述只有模块级关键词或部分测试名、没有逐字 node ID，且仓库存在记录过失败的历史运行日志（CI 全量输出、tmp 归档、账本内嵌失败摘要）；或对测试树做关键词搜索时命中被 .pyc 编译缓存污染且结果被截断。

## Discriminator
两条当时已可见的事实：①任务断言『曾观察到失败』却未给 node ID ⇒ 失败的精确记录必然已存在于权威归档（full-run 日志的 FAILED 行）；②关键词 grep tests/ 只见 __pycache__ 命中且被 head 截断 ⇒ 同名源文件可能不止一个，『关键词→文件』映射不唯一。二者把『所有同名测试×所有负载上下文』缩成『先从归档解析唯一失败 node』。

## Short path
- 未知量①：到底哪个测试失败过 → 在历史运行日志/CI 归档 grep 该关键词的 FAILED 行，解析精确 node ID、断言与数值（如 P95=209.7>200）
- 未知量②：隔离是否过 → 仅对该 node ID 做少量隔离复跑
- 未知量③：是否负载相关 → 上一级负载上下文复跑（所在 suite 批；必要时直接引用全量日志对照，不本地重跑全量）
- 未知量④：统计机制 → 直读该测试的采样/分位实现（如 N=10 时 P95 索引即最大样本）
- 落定性档、以 evidence:// 引用收口；若真实目标与任务标题所指不同，回写更正台账

## Stop conditions
- 权威归档已解析出唯一 node ID 且失败形态与任务描述吻合（或已回写更正）→ 停止目标搜索，转入复现梯度
- 归档中确无该关键词失败记录 → 才降级为跨 suite 枚举同名测试文件的宽发现

## Verification
- 复现循环针对的 node ID 与历史 FAILED 行逐字一致
- 定性结论至少覆盖隔离与批/suite 两级负载证据
- 若中途发现复现对象与标题所指不同，显式终止旧循环并更正记录，而非让两条线并存

## Counterexamples
- 任务书/账本已内嵌完整 node ID（suite 路径+函数名）→ 直接用，跳过归档检索
- 失败是本轮现场刚观测到的 → 当前 traceback 即权威记录，无需翻历史
- 全仓该名字唯一对应一个测试文件 → 关键词映射无歧义，一次确认即可开跑
- 任务意图是模块级全量抖动审计（该名字下所有用例都要扫）→ 枚举同名文件就是任务本身
