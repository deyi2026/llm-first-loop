---
method_id: flip-gate-decision-probe-named-observation-channel-first-932c22906c23
name: flip-gate-decision-probe-named-observation-channel-first
description: 用户征求『是否把某运行时门从 shadow 切到 enforce』的意见时，决定性未知是『shadow 期观测回执是否存在、达标没有』。观测通道的确切名字（事件前缀、data 目录、状态文件）只由实现源码定义：先按模式键做一次 content grep 定位实现文件，读实现同时取得 enforce 语义与观测产物名，再按名精确查事件流和落盘目录，最后核运行 release 是否包含该特性。泛化文档搜索、枚举测试文件、宽 scope 事件流查询都拿不到这些名字，只会换措辞重试或读回自己的 action trace。按名查得的阴性回执（查无）本身就是可引用的裁决证据。
aliases: shadow 切 enforce 前先查观测回执, 要不要切 enforce 怎么判断, 模式切换门槛怎么核实, shadow 期没数据能不能上 enforce, 先读门实现再查 shadow 落盘
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:2ef924ad-22aa-459c-881a-b100534b16c2:323:53be7c473cba39881a4a
evidence_refs: learning:learn:b42ef6afa0af
created_at: 2026-10-29T13:12:16.449503+08:00
updated_at: 2026-10-29T13:12:16.449503+08:00
---
## Trigger
用户问是否把某运行时门/特性从 shadow（仅观测）切到 enforce（实际生效），且当前上下文没有该门 shadow 期的观测数据回执；或同类『切换门槛是否已满足』的裁决请求

## Discriminator
提问时刻即可点名的关键事实类：shadow 观测回执是否存在；且三态语义、默认值、观测事件/产物名全部由仓内实现源码唯一确定——一次按模式键 content grep 即可同时拿到实现文件真实路径与其中常量。这说明权威下一跳是『读实现拿名字』，而不是泛化关键词搜文档、枚举测试或扫全仓历史

## Short path
- 按问题点名的模式键/特性名做一次 content grep（如 cog_runtime_mode），定位 config 默认值与实现文件；注意 search 命中行的显示路径可能省略仓库根前缀（如缺 src/），read 前先核对真实路径
- 读实现文件，一次取得两个未知量：enforce 语义（阻断型还是注入型、重注入上限、兜底降级）+ shadow 观测通道的确切产物名（事件前缀、data 目录、状态文件路径）
- 用刚学到的确切名字查观测产物：按事件前缀精确查事件流、列状态文件目录——区分『门运行过』（gate_state 类文件存在）与『观测回执存在』（事件/聚合统计存在）
- 核运行版本：git log 与 release 绑定确认线上代码是否含该特性、env 变更要经 publish+restart 才生效
- 每个切换门槛问题各有阳性回执或按名核验的阴性回执后即停止并给意见；阴性结论注明覆盖范围与未核验边界

## Stop conditions
- 模式语义与默认值已从实现源码确认（不靠测试枚举推断）
- 观测回执存在性已按实现定义的确切名字核验，『在/不在』均有明确结论且能区分门运行痕迹与观测数据
- 运行 release 是否包含该特性、env 何时生效已确认
- 文档搜索 miss 后不换措辞重试，不枚举测试文件确认语义

## Verification
- 最终意见中每条切换门槛都对应一个可指名的回执，或一次对实现中定义的确切事件名/目录的阴性核验
- 引用的 enforce 行为（注入型、上限、兜底）能指到实现源码具体位置
- 『查不到』类断言只出自按名查询，并附覆盖范围说明与置信度标注

## Counterexamples
- 功能没有 shadow/enforce 观测语义（纯新特性上线决策）——无观测通道可查，应改为收益/风险/回滚评估
- shadow 观测数据已由用户或现成统计给出且达标——直接裁决，不必回实现源码定位通道
- 开关语义不在本仓代码（外部 SaaS/平台级开关）——权威在供应商文档，grep 实现无意义
