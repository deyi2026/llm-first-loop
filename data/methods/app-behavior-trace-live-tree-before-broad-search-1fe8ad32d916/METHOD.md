---
method_id: app-behavior-trace-live-tree-before-broad-search-1fe8ad32d916
name: app-behavior-trace-live-tree-before-broad-search
description: 用户问『为什么本系统自己会出现某行为』（如发消息为何新开会话）时，权威真值是当前工作树里『前端构造请求的代码 + 后端处理分支』的因果链，而不是 docs 摘要、.releases/<hash>/ 快照副本或 .venv/node_modules 噪声。正确起手：先做一次廉价结构列举（ls 根目录）确定 live 前后端目录，再读前端 wire 类型定义拿到精确字段名（如 new_session/session_id），只对该字段在 live 树内定向 grep，读两端源码即停。判别信号：搜索命中被 .releases 重复快照或 site-packages 主导、失败回执已登记路径不存在并建议停止——都说明在枚举副本空间，应收窄作用域而非换词重搜或重试同一路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:68d4bee4-e397-4244-b5a3-3689fb21fcb4:1:ce1444d6b68774fe1d71
evidence_refs: learning:learn:12709df54629
created_at: 2026-10-13T21:18:02.055633+08:00
updated_at: 2026-10-13T21:18:02.055633+08:00
---
## Trigger
用户询问本产品/本系统自身运行行为的成因（『为什么发X会Y』类问题），答案需定位到实现该行为的代码因果链

## Discriminator
knowledge-at-time 可观察事实：搜索命中大量来自 .releases/<hash>/ 重复快照、evals/**/.venv/、node_modules 等非权威副本（说明在扫副本而非真值源）；或 miss 回执已点名与问题直接相关的自家子系统文档（如 Web V2 协议差异文档）指明代码所在子系统；或失败回执已登记路径不存在并明示停止——任一出现即表明下一步应收窄到 live 工作树，而非换词重搜或原样重试

## Short path
- 判定问题类：『系统为何自己做X』→ 真值在 live 工作树的前端构造点与后端处理分支，docs 与快照只是线索不是答案
- 一次廉价结构列举（ls 根目录）确定 live 前端目录与后端模块目录，替代目录名猜测（如猜 web/）与全库内容搜索
- 在 live 前端树读 wire 类型定义（请求体接口），得到可定向 grep 的精确字段名（如 new_session、session_id）
- 仅用该字段名在 live 前后端树内 grep：定位前端置位点（store/事件处理）与后端分支（routes 处理函数）
- 读到两端源码、因果链（前端标记→请求字段→后端新建分支）闭环即停；若与线上观测不符则改查部署版本/日志，不再本地扩搜

## Stop conditions
- 前端构造点与后端处理分支均已取得源码级证据，行为成因闭环
- live 树证据与实际观测（事件流/日志）矛盾时，停止本地扩搜，转向核对部署版本或运行时状态

## Verification
- 结论引用的字段/分支确认位于当前工作树，而非 .releases 快照或第三方依赖包
- 两端对齐：前端请求构造处设置的字段与后端触发该行为所读取的字段同名同义
- 用事件流/日志中的实际行为序列印证因果链（如每条消息恰对应一个新 session_id）

## Counterexamples
- 询问外部库/框架自身行为（如 langgraph 为何重试）时，.venv 内 vendored 源码或官方文档才是权威，live 工作树优先不适用
- 考古/回归定位（『该行为何时引入』）恰恰需要 .releases 快照序列做时间轴对比，排除快照反而错误
- 问题已被自家文档完整回答（如 wake 分叉协议文档）时，直接读该文档即停，无需代码追踪
- 本地树与部署版本可能漂移且用户问的是线上行为时，只读本地树会误判，必须核对部署版本
