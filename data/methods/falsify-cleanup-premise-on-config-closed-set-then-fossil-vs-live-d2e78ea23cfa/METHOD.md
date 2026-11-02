---
method_id: falsify-cleanup-premise-on-config-closed-set-then-fossil-vs-live-d2e78ea23cfa
name: falsify-cleanup-premise-on-config-closed-set-then-fossil-vs-live
description: 继承的清理/效率建议以『配置里存在某陈旧引用或噪声需清除』为前提时，第一步不是全仓宽搜，而是对配置权威闭集（providers.json/runtime.toml/.env 这类小闭集）定点 grep 裁决前提真假：宽搜会把历史归档与数据记录的命中混入，误把化石当活问题。前提证伪后，再用错误原文定位 src raise 点与邻近注释归因，用日志最后写入时间 vs 最近重启时间判定噪声活跃性，用容器类别（当前配置=可改 vs 历史 session/job 事实记录=不可改写）路由修复：改配置 / 消费端可读失败 / 不动并如实报告。与『断言经定义面裁决』『建议前提新鲜度复核』卡互补：本卡多出『日志停更=化石』与『数据≠清理目标』两条判别。
aliases: 建议说配置里有其实没有, 错误日志刷了七万次还活着吗, 老日志报错算历史还是现行, 历史会话里的模型引用能清吗, 按建议清理前先证伪前提, 化石噪声别当活故障修
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:3030:ccc5e27a86bc25e335da
evidence_refs: learning:learn:c554464d5205
created_at: 2026-11-01T17:38:44.932135+08:00
updated_at: 2026-11-01T17:38:44.932135+08:00
---
## Trigger
继承的建议清单（效率/清理类）中某条断言『配置/运行时里存在某陈旧引用或错误噪声』并要求清除，执行前需先裁决该前提；或全仓 grep 目标 token 的首批命中落在 data/private-archive、历史 run dump 等归档路径时。

## Discriminator
建议文本本身已点名容器类别=『配置』，而仓库配置权威面是小闭集（键名级定点 grep 一次即出真假）；同时全仓命中的首批路径（如 data/private-archive/.../run-state.json）自身已标明是历史归档而非配置；日志最后写入时间停在重启之前，说明巨大错误计数是化石而非现行故障。

## Short path
- 对建议声称的配置闭集（providers.json/runtime.toml/.env）定点 grep 目标 token：命中→前提真，走正常清理；零命中→前提假，转下一步
- 用错误消息原文在 src 检索 raise 点并读邻近注释（常已写明成因，如『配置漂移后每个 job』）：确立错误真实生产路径与触发条件
- 判活跃性：日志尾部最后写入时间/轮转边界 vs 最近重启时间——停止增长=化石噪声；重启后仍增长=活跃生产者，转找活跃 writer
- 定位引用容器类别：当前配置（可改）vs 历史 session model_ref / job source_model 等事实记录（不可改写）；化石且只存在于历史记录→不改数据，报告前提错误并列消费端修复选项（可读失败+停重试）供用户裁决
- 停止：该不该清、清哪里、是否仍在发生三个未知量均已用权威面证据回答

## Stop conditions
- 配置闭集已裁决、错误生产点已定位、噪声活跃性已判定、容器类别已分类——清理建议的可行性结论已可给出
- 若发现日志在重启后仍在增长，立即转入活跃 writer 排查，不再做归档/历史考古

## Verification
- grep providers.json/runtime.toml/.env 键名均零命中，是『前提假』的直接落盘证据
- 错误原文在 src 的 raise 点唯一，且 raise 文案与日志行文逐字一致
- 日志最后写入时间早于最近重启时间；引用计数与历史记录条数（如 77 个 session）互相印证，证明残留只在事实记录层

## Counterexamples
- 配置闭集确有该键：前提真，直接清理并验证，无需活跃性考古
- 日志仍在持续增长：是现行故障，必须定位正在写入的 writer，『历史遗留』结论会掩盖真问题
- 引用容器是缓存/可再生派生产物而非事实记录：允许重建或清除，不适用『不改写历史』约束
- 建议只描述症状未声称位置：没有闭集可先查，错误串定位或受控宽搜才是合理第一步
