---
method_id: retrieval-hit-closes-discovery-no-storage-guessing-4ffa43cd59e2
name: retrieval-hit-closes-discovery-no-storage-guessing
description: 当结构化检索/水合工具（search_records、索引、API）已返回目标条目的完整权威内容（定义、关键数字、验证状态）后，未知量已经从'位置性'（数据存在哪个文件）转为'语义性'（基于内容做什么）。此时不应再用猜测的文件系统路径去枚举底层存储目录；下一步应直接沿内容的因果生产者（代码路径/上游机制）行动。只有水合内容字段缺失、被截断或需要 provenance 级取证时，才下降到原始存储定位。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:918cb167-56ff-4666-9f15-32f98b72c356:534:8060d9fca588a1e34c3e
evidence_refs: learning:learn:ed12fb9ff606
created_at: 2026-10-06T16:52:02.682928+08:00
updated_at: 2026-10-06T16:52:02.682928+08:00
---
## Trigger
检索/水合工具已命中并展示目标记录的完整内容（scenario、指标、verification_state 均可见），但后续动作转为对同一数据的底层存储做逐个猜测路径的文件系统枚举（如连续尝试多个候选目录名、错误项目根下的 find、宽 grep 直至超时）。

## Discriminator
两点当时已可见：(1) search_records 回执已含缺口的确切定义与审计数字且标记 verified——未知量（缺什么遥测）已被回答，不再是'记录内容在哪'；(2) 同回合输出已给出命名空间与仓库布局证据（pwd=llm-first-loop-mirror，methods 记录形如 data/methods/record-use-*），而后续 find 却用了非 mirror 的错误根目录、路径猜测与 observed 布局均不匹配。满足 knowledge-at-time：不需要事后结果即可判定磁盘狩猎是零收益分支。

## Short path
- 读 search_records 回执，提取缺口定义与关键数字（未知量：缺口到底是什么）→ 已答
- 沿内容的因果生产者进入代码：grep 缺口命名的机制（record_use）在 src/ 的定义与调用点（未知量：决策事件在哪发射）
- 读相关 post_run/hook 代码，实施最小增量改动（补一条决策侧事件，字段与既有 ledger 扫描语义对齐）（未知量：最小改动是什么）
- 补单测并跑相关回归；数字断言对回执/RESULT 校验
- 停止：全程不需要定位经验记录的原始存储文件

## Stop conditions
- 水合内容已回答当前未知量
- 代码路径已定位且改动被测试验证
- 连续两次存储路径猜测零命中——立即中止该分支

## Verification
- 发起任何原始存储定位命令前自检：上下文中已水合内容是否已回答未知量？若是，该命令必须被取消
- 审计路径猜测次数：同一未知量下 ≥2 次零命中猜测即为违规信号
- 确认最终改动引用的事实全部来自回执/代码，而非中途磁盘狩猎的产物

## Counterexamples
- 任务目标本身就是迁移/修复存储文件布局——存储定位即目标，不是摩擦
- 检索工具不可用、返回 legacy_unclassified 或只有截断摘要，需要 provenance 级核验时，读原始记录合法
- 记录含并发写者且结论须为终局断言时，应按 fresh-read 重读权威记录，而非依赖缓存的水合内容
