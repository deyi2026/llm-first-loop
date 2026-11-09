---
method_id: stuck-vs-idle-split-before-cross-session-wake-recommendation-0e2b12764422
name: stuck-vs-idle-split-before-cross-session-wake-recommendation
description: 用户要求直接联系/唤醒其他停滞会话（直发或操控浏览器）时，先枚举自身通道的触达语义：文件收件箱=纯拉取、仅对方下次 run 启动时读取；agent_message=仅直系 parent/child；浏览器 pages 清单=本实例实际可控页面的真值。再对每个目标按事件流三分类：有 llm_decide=活跃→直接发单一请求；零事件=纯停滞→请用户在面板发一条唤醒消息；只有机械事件（compaction/gate 循环）而无其后任何 llm_decide=基础设施卡死→消息送达也读不到，唤醒未必有效，须一并呈报宿主层修复。呈报前先 resolve 对方发来的 pending 请求，使唤醒落地即可行动。不以浏览器向会话输入框注入用户消息（冒充用户意志）。补足『最近时间戳=活跃』会误判机械事件为活跃的缺口。
aliases: 怎么叫醒卡住不动的会话, 能给另一个会话发消息吗, 会话一直没反应是不是坏了, 用浏览器替我给那个会话发条消息, 收件箱消息对方什么时候能看到, 会话反复报compaction是不是卡死了
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:4069:5ad0cf565590c3ae5a66
evidence_refs: learning:learn:0fc5e4ddcf46
created_at: 2026-11-09T08:53:51.386077+08:00
updated_at: 2026-11-09T08:53:51.386077+08:00
---
## Trigger
用户要求本代理直接给指定停滞会话发消息、或通过操控浏览器/面板代为发消息；或询问跨会话消息能否送达、何时会被读到

## Discriminator
目标会话事件流最近条目的构成：只有机械事件（compaction_gate/gate 循环、异常重试）且其后无任何 llm_decide → 基础设施级卡死（唤醒也可能读不到）；完全零事件 → 纯停滞（一条用户消息即可唤醒）；存在 llm_decide → 活跃。若『最近时间戳新鲜』仅来自机械事件，按活跃处理会误判。

## Short path
- 枚举通道触达语义：help 收件箱=纯拉取、对方下次 run 启动才读；agent_message=仅直系 parent/child；浏览器 pages=实际可控 tab 真值（无面板页即物理不可达）
- 对每个目标查 event_stream，按『机械事件 vs llm_decide』三分类：活跃 / 纯停滞 / 基础设施卡死
- 目标曾发来的 pending 请求若本会话可闭环，先 resolve（对方被唤醒后收件箱里直接有答案）
- 分流呈报：纯停滞→请用户面板发一条唤醒消息并附建议文案；卡死→额外请求宿主层诊断并让用户回报现象；活跃→无需用户动作
- 拒绝以浏览器向会话输入框注入消息（等于冒充用户输入）；如存在以代理身份或用户显式授权的官方注入入口，作为替代方案提出

## Stop conditions
- 每个目标分类已定、用户侧动作已明确（唤醒文案或宿主诊断请求）、自身 pending 入站已 resolve 或确认无法处理，即停，不再枚举更多通道或反复重查活跃度
- 用户所需答案只依赖通道边界与分类结论时，不等待对方实际回应即可答复

## Verification
- 卡死分类与异常面互证：exception_log 中该会话存在对应机械故障（如 compaction/gate 报错）且时间窗吻合
- 唤醒建议执行后做一次有界复查：event_stream 是否出现新 llm_decide、收件箱 pending 是否被消费；不循环催办

## Counterexamples
- 目标会话在自身直接拓扑上（parent/child）：agent_message 可达，直接发消息即可，无需停滞/唤醒框架
- 平台存在官方会话复用/注入入口且用户明确授权：可直接走该入口唤醒，不必把动作推回用户面板
- 目标最近有 llm_decide（真活跃）：只需发单一明确请求并做一次有界复查，卡死/停滞分类不适用
- 通道为推送型（对方无需 run 启动即被通知）：『下次 run 才读』前提不成立，应改判通道可达性而非唤醒
