---
method_id: store-api-existence-oracle-over-layout-scan-2cef3d6550d8
name: store-api-existence-oracle-over-layout-scan
description: 接手交接文档/外部报告并执行批量持久化操作（归档、迁移、回填、清理）时，文档中基于物理布局扫描得出的记录存在性与成本结论（『N 条无事件日志、预计回填 X MB、耗时 T』）不可直接采信或用同一布局法复测：本会话已读的 store 消费方源码（如 backfill 路径里的 store.exists()/store.read()）表明存在语义由产品 API 定义，且 API 兼容平铺文件与分段/滚动目录等多种形态。存在性必须经同一 API 重导出，否则布局假阴性会导出整条错误的成本与风险模型（本集『89 条缺失、178MB 回填、10-30 分钟』实为分段目录形态，真实回填为零、耗时 39 秒）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0f1ec2ed-fa63-461c-ac5d-5b4d2342f534:0:bc5bd33c0085ca95ed0e
evidence_refs: learning:learn:2b11fb348bba
created_at: 2026-10-21T01:04:21.363115+08:00
updated_at: 2026-10-21T01:04:21.363115+08:00
---
## Trigger
跨会话交接文档或外部报告给出针对代码库自有 store 记录的存在性/成本断言（缺日志、需回填、预计体积或耗时），断言源于对磁盘布局的直接扫描（平铺路径存在性检查），当前要据此执行批量非幂等操作。

## Discriminator
本次已读的 store 消费方源码直接暴露产品判据：如 _event_backfill 内 `if not store.exists(sid)`、`store.read(sid)`——存在语义挂在 store API 上而非任何特定路径形态；因此凡与 API 判据不一致的布局扫描结论，在被用于执行决策前即为未验证状态。

## Short path
- 读交接文档并分拣断言：纯状态断言（文件数、指针值、current 指向）核对外部状态即可；存在性/成本断言单独标记，不照抄其布局扫描法复测
- 对每条影响决策的存在断言，用产品 API 重导出：对文档声称『缺失』的记录子集调 store.exists()（或实例化 store 批量查）
- 出现分歧（API 说存在、布局说缺失）时，查 store 物理形态实现（分段/滚动目录），确认 API 抽象了多种布局，修正成本模型
- 按修正后的成本模型执行：干跑→单条试点→批量→指针/外键处置
- 收尾核验走同一 API（如 EventStore.read() 确认归档事件存在），不再用路径检查作终验

## Stop conditions
- 文档中影响执行决策的存在性断言已全部经 store API 重导出且分歧已解释
- 批量动作完成后 API 级读回核验通过（status 与事件均确认）

## Verification
- 对文档声称『缺失』的记录抽样或全量 store.exists()，与布局扫描求差集；差集非空必须先解释物理形态再行动
- 执行后核验与判据用同一通道（API 读回），避免核验通道与决策通道不一致

## Counterexamples
- store 本无 API、就是普通文件目录（静态文档、导出目录）：路径检查即正确判据，无需引入 API
- 审计对象恰是 API 本身是否可信（数据损坏、store bug、恢复场景）：必须直查物理布局，API 结论反而是被审对象
- 记录量极大且逐条 API 调用昂贵：可先用布局批量扫描初筛，但任何『缺失』结论在触发回填/删除前须经 API 抽检确认
- 已确认该 store 只有单一平铺形态、布局与 API 一一对应：两法等价，方法无增量收益
