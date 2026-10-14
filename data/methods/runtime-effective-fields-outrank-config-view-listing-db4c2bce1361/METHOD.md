---
method_id: runtime-effective-fields-outrank-config-view-listing-db4c2bce1361
name: runtime-effective-fields-outrank-config-view-listing
description: 验收指标绑定运行时生效态（如 effective_provider_count=6/29）而系统是多层配置叠加（持久化配置文件 + 运行时动态注入 overlay）时，配置管理视图的阴性（providers 列表缺条目）不构成『注册失败』证据。先用同一响应中的 runtime_*/effective_* 聚合字段裁决计数，仅当 effective 视图也不达标才去查注入链路；最终以一次生产往返交叉验证。本集曾因 5≠6 触发 git log、providers.py 优先级链、factory.py 路径试错（2 次失败读）等长排查，而真值一直在同一响应的 effective_* 字段里。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1897dc0c-c278-413c-b54d-22c50b97372f:743:5bebf71b9f1312755faa
evidence_refs: learning:learn:4794a0c332cb
created_at: 2026-10-14T10:02:26.972934+08:00
updated_at: 2026-10-14T10:02:26.972934+08:00
---
## Trigger
对多层配置来源的活系统执行验收计数/状态核验：持久化配置文件与运行时动态注入（外部模块 overlay）叠加生效，且查询端点的单次响应同时暴露 configured_* 与 runtime_*/effective_* 成对字段；或验收口径明确写的是『生效计数』而非『配置条目数』。

## Discriminator
同一 snapshot 中出现 configured_default_model 与 runtime_default_model 成对字段、且响应标注 source=local——证明 providers 数组只是配置文件管理视图，运行时叠加条目的真值在响应其余部分的 effective_*/runtime_ 聚合字段。首轮 raw 结构只看了 60 行截断预览就下了『5≠6、deepseek-web 未注册』判断，未先读全响应确认是否存在 effective 聚合。

## Short path
- 拉取 provider snapshot 时读完整响应（勿用截断预览裁决计数）；未知量：effective_provider_count / effective_model_count 是多少
- 看到 configured_*/runtime_* 成对字段存在 → 从 effective 聚合字段读真值；providers 数组缺条目仅记为配置视图事实，不触发根因排查
- 若 effective 视图也不达标 → 才查注入接缝：env 中 *_MODULE 配置、启动日志有无 warning、注册模块的降级语义（无 warning 且空 = 未配置或健康两态，非单义失败）
- 生产真机往返验证通道真实可用：指定目标 provider 发真实请求，日志 provider= 与外部侧证据双确认
- effective 达标且往返成功 → 收口，停止发现

## Stop conditions
- effective 聚合字段达到验收值且生产往返由目标 provider 真实承载
- effective 视图也不达标且注入接缝已定位（模块未配置/加载失败原因/降级路径），进入修复而非继续枚举

## Verification
- 确认最终计数来源字段与验收口径同名（effective_* 而非配置数组长度）
- 生产往返日志显示目标 provider 真实承载请求，且外部侧有独立证据
- 配置视图与 effective 视图的差值能用已知 overlay 机制解释（如外部模块注入的条目数）

## Counterexamples
- 端点只暴露单一配置视图、无 effective 字段 → 配置阴性即真实，需直接查注入链路，本方法无判别力
- 验收口径本身就是『配置文件应含 N 条』（管理面一致性检查）→ 应以配置视图为准，effective 字段反而无关
- effective 聚合自身有缓存/刷新滞后缺陷 → 不能只信单字段，必须生产往返交叉
- 两视图不一致本身就是待修缺陷 → 需双侧核对并解释差值，而非取 effective 一读了事
