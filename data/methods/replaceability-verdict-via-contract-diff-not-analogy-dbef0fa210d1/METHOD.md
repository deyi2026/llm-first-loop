---
method_id: replaceability-verdict-via-contract-diff-not-analogy-dbef0fa210d1
name: replaceability-verdict-via-contract-diff-not-analogy
description: 用户问『新装/可用的 X 能否替代系统内组件 Y』，且 Y 身份易与同类/同名先例混淆时：先把 Y 钉死在权威契约工件上（wire 常量+模块 docstring、设计文档状态行：endpoint/alias/部署形态/资格状态），用缓存 mtime/catalog 钉住 X，再逐字段 diff 契约必需能力得出按代价排序的缺口清单，并按 Y 的依赖形态（如 shadow 无生产依赖）把决策重构为『冻结集基线对比』而非上线风险。禁止用名称相似的先例给 Y 定性；事件流已点名路径时直读，不再宽域重搜简称。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:772ada61-13b9-4021-9c80-9d2916e05c61:21:1bb7a4e54edf01942cbf
evidence_refs: learning:learn:6543a9d205b4
created_at: 2026-10-15T20:10:50.853433+08:00
updated_at: 2026-10-15T20:10:50.853433+08:00
---
## Trigger
用户以简称引用系统内既有组件 Y，并问新安装/可用的 X 能否替代它；Y 的性质可能与历史同类组件（路由/判断/检索等）混淆，仓库内存在 Y 的契约源文件与治理文档

## Discriminator
事件流或搜索命中的文件头已点名 Y 的契约路径，且契约文件头部常量+docstring 可一次读出接口字段、逐题状态语义与部署形态；本地缓存 mtime 已唯一钉住今天的安装物。二者齐备时主未知量只剩『契约字段级 diff』，更宽的名称/语义搜索都不再缩小它

## Short path
- 钉 X：以本地缓存 mtime/catalog 唯一确定今天实际落地物（如 HF hub 目录当日快照），不再枚举端口/包名等旁证
- 钉 Y：沿事件流/命中文件头已点名的路径直读契约源文件头部，取得 endpoint/alias/接口字段/逐题状态语义
- 读治理文档状态行：确认 Y 当前依赖形态（shadow/生产）、资格状态与冻结评测集
- 逐字段 diff：把契约必需而 X 原生缺失的能力列为按代价排序的缺口（如逐题完整概率分布、多题批、语义 unknown 与协议 invalid 分流）
- 按依赖形态重构决策：无生产依赖时问题变为『能否在同一冻结集上打过基线』；以一个需用户授权的评测提议收口并停止

## Stop conditions
- Y 的每项断言均可回溯 file:line 或文档节号，且无一条来自名称相似先例
- 缺口清单覆盖契约全部必需字段；决策框架已由依赖形态确定

## Verification
- 回答中关于 Y 的表格逐项核对契约源文件行号与设计文档节号
- 自查所引历史先例的组件类别与 Y 一致才可作依据，不一致则显式撤回（如判断服务≠路由模型）

## Counterexamples
- Y 是自文档化本地库、唯一未知是调用方清单：契约 diff 无增量，应直接走定义面+callsite 枚举
- Y 是无文档黑盒第三方：无契约工件可 diff，只能实测探边界，本方法不适用
- X 与 Y 同类且兼容矩阵已知：直接作答，不必重推契约
- 用户问的是偏好/预算取舍而非能力可行性：无需契约绑定
