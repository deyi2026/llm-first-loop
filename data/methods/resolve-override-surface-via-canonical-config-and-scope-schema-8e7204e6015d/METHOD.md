---
method_id: resolve-override-surface-via-canonical-config-and-scope-schema-8e7204e6015d
name: resolve-override-surface-via-canonical-config-and-scope-schema
description: 当用户要求『把某类任务的默认值（模型/成本档/开关）改为 X』时，第一个未知量不是『X 出现在仓库哪里』（全库关键词扫描只会命中 .env 备份和 CHANGELOG 噪音），而是『该任务类别的执行上下文里，这个值由哪一层配置合法拥有』。先读权威配置文件：其结构+行内注释通常自述分层架构与既有 override 先例（谁被钉过、scope 边界、回滚方式）；再读 schema 门禁（scope 白名单/加载器）枚举合法面；最后把改动放在最窄的已授权面（如派发点的可选字段，未设值行为逐字不变），绝不扩大到全局默认，也不发明闭集 schema 会拒绝的配置面。
aliases: 给某类任务换模型先看配置分层, 改任务默认模型应该改哪一层, 排期任务钉模型不动全局默认, 任务级模型覆盖放哪个配置面, 按任务类别改默认值怎么找落点
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a621f83f-a9c5-4c0f-ab5d-b84010eebe14:292:6ca2a5f979e98e68eae4
evidence_refs: learning:learn:6fb88d1aee78
created_at: 2026-10-31T21:30:48.465273+08:00
updated_at: 2026-10-31T21:30:48.465273+08:00
---
## Trigger
用户要求改变某类任务（而非某条命令单次）的默认模型/成本档/行为，且系统存在多层取值链（全局默认→服务级覆盖→会话/调度级），目标类别不等于现成的服务通道；或全库内容搜索开始在 .env 备份、CHANGELOG、STATUS 文档里反复扫同一个词根。

## Discriminator
权威配置文件（本例 runtime.toml）里既存的 override 块及行内注释已写明：取值分层、先例机制（仅 wecom 钉模型）、『其余服务仍用全局默认』、回滚方式；随后 resolver 的 _SERVICE_SCOPED_SECTIONS 闭集白名单（llm 仅 {wecom}）显式枚举哪些 scope 被授权。这两处事实把『改哪里』从所有可能层缩到一两个合法面——它们在动手设计前就已可读，且无需全库搜索。

## Short path
- 直接读权威配置 artifact（按名可寻的 canonical config，而非全库关键词扫描）；未知量=取值分层结构与既有 override 先例，行内注释给出 scope、授权边界、回滚。
- 把任务类别映射到执行上下文（发文任务=排期班次→web 服务新会话）；未知量=变更需落在哪一层。
- 读 schema 门禁（resolver 的 scope 白名单/加载器代码）；未知量=目标层是否是合法配置面。
- 白名单拒绝该 scope 或改动会波及其他服务时，不硬闯也不改全局默认：沿既有机制（switch_model/会话级 override）在派发点（schedule 条目）加最窄可选字段，未设值路径与旧版逐字一致。
- 用权威 ref（model_catalog）核对目标值的确切标识，测试验证未钉条目零变化，再走部署门禁收尾。

## Stop conditions
- 已确认目标类别的执行上下文与唯一最窄合法 override 面，且未钉条目/其他服务的序列化行为不变。
- schema 白名单显式拒绝目标 scope 时，立即停止尝试该面，转派发点/会话层，不再换关键词重扫。

## Verification
- 未设新字段的条目持久化键集与旧版逐字节一致（老数据零变化）。
- 目标值使用权威 catalog 的精确标识，而非用户口语名（minimax-m3.1-flash ≠ minimax/MiniMax-M3.1-Flash）。
- 新钉条目派发出的会话实际以 override 值运行且有可观察来源标记（如 model_override_source）。

## Counterexamples
- 请求本身就是『全局默认改为 X』——全局层就是正确面，『找最窄面』逻辑反而错误。
- 目标恰好是已有服务通道（如企微接入）——直接复用既有 service-scoped 机制即可，无需派发点设计（那是另一张 per-service 卡的领地）。
- 配置是无闭集 schema 的开放 .env/自由键值——没有白名单可询，判别事实退化为『谁消费这个键』。
- 全新系统、配置里没有任何 override 先例——行内注释判别事实不存在，只能从消费方源码推导取值链。
