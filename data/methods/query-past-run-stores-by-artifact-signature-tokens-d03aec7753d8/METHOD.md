---
method_id: query-past-run-stores-by-artifact-signature-tokens-d03aec7753d8
name: query-past-run-stores-by-artifact-signature-tokens
description: 从运行记录/事件流/文件库找回『过去某次运行实际做了什么/错在哪』时，检索词要用目标 artifact 自身文本里会逐字出现的签名 token——错误类名、模块/包名、工具名、日志行前缀（如 ModuleNotFoundError、lark_oapi、pytest、ERROR collecting）——而不是模型自拟的任务叙事标签（“A/B 对比/证明/建议”类）。本次叙事措辞连续 miss，签名查询一次即命中既有方法卡与 tmp 日志中的 52 个失败目标。首次 miss 回执就是措辞类判决：换 token 类，不换叙事措辞、不盲目换 store 续试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:de7f7e47-443e-42f9-9513-57ee99c8a21e:27:35e235cadc1ad92b106e
evidence_refs: learning:learn:fef8873d3e6a
created_at: 2026-10-13T03:41:36.204750+08:00
updated_at: 2026-10-13T03:41:36.204750+08:00
---
## Trigger
无活动 goal、也没有直接指名答案 artifact 的 provenance edge，需要从 records/event_stream/search_docs/文件库检索过去某次运行的具体事实（命令串、失败目标、回执）时；尤其是叙事措辞已收到 miss 回执之后。

## Discriminator
这些 store 按字面 token 匹配，而目标记录文本由工具生成：miss 回执『未找到匹配 A/B 对比 证明收集 依赖缺失』当时已证明叙事词不在记录文本中；同时 search_files 命中的 uv.lock/日志行显示 artifact 词汇（reportlab、ERROR collecting、ModuleNotFoundError、lark_oapi）才是库内实际用词。

## Short path
- 先固定唯一未知量：过去那次运行的答案在哪个具体 artifact（tool_call JSON、失败日志、回执）。
- 首查可用叙事词；一旦收到 miss 回执，立即把查询改写为目标 artifact 词汇表的签名 token（错误类名/模块名/工具名/日志行前缀），不换叙事措辞再试。
- 用签名 token 查 records/event_stream/search_files；命中后优先打开含原始 tool_call/日志行的条目，从原文逐字抄出命令与目标清单。
- 用第二独立签名（日志文件名+时间戳 ls、回执 ref）交叉确认 artifact 身份后再行动。
- 对抄出的目标清单做『数量=源日志标记数且逐个存在』的前置校验，通过即停止检索、进入复跑。

## Stop conditions
- 所需命令与目标清单已能从原始记录逐字指认，并与第二个独立来源（时间戳/ref）交叉一致。
- 签名查询已覆盖已知错误面（如全部 ERROR collecting 块），无未解释缺口，不再追加变体查询。

## Verification
- 每个找回事实在命中条目原文中逐字可见（命令串、目标名），而非转述。
- 抽取目标数与源日志标记数一致（ERROR collecting 块数=目标数），且每个目标存在。
- 复跑回执（退出码、passed 数、missing=0）与找回清单完全对应。

## Counterexamples
- 已有命名 provenance edge 直指答案（最新停点文档、被点名备忘、git delta）时，直接沿 edge 读，不要检索——那是 resume-continuation-via-named-provenance-and-git-delta 的适用面，本方法只覆盖必须检索的场合。
- 目标 artifact 是人写散文（设计决策、策略文档），正文本来就由叙事词构成，签名 token 反而会 miss；应按该文体的措辞检索。
- 冷启动宽发现：对失败原因完全无知、拿不出任何错误类名/模块名时，先做一轮宽发现取得第一手症状 token，再进入本方法，而不是空猜签名。
