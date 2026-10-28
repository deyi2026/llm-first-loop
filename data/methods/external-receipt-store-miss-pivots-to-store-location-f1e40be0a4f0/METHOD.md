---
method_id: external-receipt-store-miss-pivots-to-store-location-f1e40be0a4f0
name: external-receipt-store-miss-pivots-to-store-location
description: 带外回执（人工审批面板、外部系统通知）已确认某记录存在并变更，而本侧假定的存储位置查询 miss 时，该 miss 证伪的是存储位置而非记录存在性：优先沿领域经验/布局笔记定位权威持久层（如审计流水与提交目录分区、data_dir 随进程 cwd 漂移），再按 ID 精确核对状态与时间戳，避免家目录/全库枚举和无界搜索。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:628:034ad6363ae3ceba9579
evidence_refs: learning:learn:7efcabf2e542
created_at: 2026-10-18T00:38:52.159509+08:00
updated_at: 2026-10-18T00:38:52.159509+08:00
---
## Trigger
收到带外回执（人工面板审批、外部系统登记通知）确认某记录已存在/已变更，且必须在本侧持久层核实现状后才能继续执行

## Discriminator
回执已给出记录 ID 与时间戳（存在性为真）；若假定 store 处 miss 或只见陈旧条目，这是位置证伪信号——真实记录落在另一持久层；仓库/领域常留有以子系统命名的经验笔记（split-brain、data_dir 漂移类）直接记载权威落盘路径

## Short path
- 把任务缩成单一未知量：该记录 ID 在权威持久层的当前状态
- 先查领域经验/布局笔记或记录索引，确定该类记录的真实落盘位置，而非枚举目录
- 在权威 store 按 ID 精确检索，读取 status 与 reviewed_at 等字段
- ID、状态、时间戳与回执三方一致即停止发现，进入执行阶段

## Stop conditions
- 权威 store 中该 ID 的状态与外部回执一致（时间戳量级吻合），唯一未知量已消解
- 权威 store 亦 miss 时才转入 store 定位诊断（进程 cwd/env、data_dir 锚定、经验笔记），仍不做全库枚举

## Verification
- 实际读取路径与子系统文档/经验笔记记载的持久层一致，而非平行副本或发布快照
- 记录 ID、status、reviewed_at 三者同时匹配回执，防止只匹配 ID 的同名异条

## Counterexamples
- 无外部存在性确认时（ID 可能笔误），miss 更可能表示记录不存在：应回查 ID 来源而非寻找替代 store
- 单持久层且无 split-brain/漂移史的系统：miss 即 absent 或被过滤，大范围 store 搜索是过度反应
- 最终一致/复制延迟型存储：写入后立即 miss 只需有界重读等待，而非另寻 store
