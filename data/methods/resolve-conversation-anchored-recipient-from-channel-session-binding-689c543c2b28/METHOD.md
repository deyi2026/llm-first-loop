---
method_id: resolve-conversation-anchored-recipient-from-channel-session-binding-689c543c2b28
name: resolve-conversation-anchored-recipient-from-channel-session-binding
description: 当请求中的目标实体锚定在当前会话（如"发给我""发到本会话"）时，接收者身份的最权威来源是把本对话接入运行时的通道自身（桥的 session 绑定/当前消息 envelope/桥配置），而非对 records/evidence 做宽关键词检索。先读通道绑定数据拿身份，再调用发送工具；只有绑定缺失或歧义时才扩大搜索或向用户确认。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:37:662986a78396b4db47c4
evidence_refs: learning:learn:2c7eafc89ef0
created_at: 2026-09-18T01:54:51.590630+00:00
updated_at: 2026-09-18T01:54:51.590630+00:00
---
## Trigger
用户要求把产物发给"我/当前会话/本群"，或任何需要"当前对话对端"身份（open_id/chat_id 等）的操作，且运行时可见存在消息通道桥（会话映射文件、桥配置或收发工具），同时尚未确定接收者标识。

## Discriminator
摩擦点（search_records 'send attachment receive_id'）之前已存在的事实：用户原话"通过飞书附件发给我"本身已把接收者锚定为当前对话对端，而当前对话正是经该飞书桥送达——因此桥的会话绑定数据在逻辑上必然已含此身份。这条事实当时即可把"如何获得 receive_id"从全库检索缩为"读桥的 session/binding 数据"一个下一跳。

## Short path
- 按 skill_load 回执的 python_executable/relative_path_base 执行产物生成（本例 md2pdf），产物生成不经过宽搜索。
- 对"发给我"类接收者：不先查 records/evidence 文档，直接定位通道桥的会话绑定数据（如 data/feishu_session_map.json、当前消息 envelope、桥配置）读取当前用户标识。
- 绑定唯一则用该标识调用发送工具；绑定多用户且无当前会话线索则用当前轮 envelope 消歧，仍不清则询问用户。
- 校验发送回执（message_id）成功且接收者与绑定数据一致后停止。

## Stop conditions
- 已从通道绑定取得当前会话对端唯一身份，且发送工具返回成功回执（message_id 等）。
- 绑定数据缺失或多义、且当前 envelope 也无法消歧 → 停止自查，直接向用户询问接收人。
- 发现发送工具自身默认回复当前会话（无需显式 receive_id）→ 直接调用一次并验证回执，跳过身份解析。

## Verification
- 发送回执成功并返回 message_id；所用接收者标识来源于当前会话绑定/envelope，而非过期记录或猜测。
- 发送前确认产物文件真实存在且非空（如 PDF 字节数合理），避免发出损坏附件。

## Counterexamples
- 接收者是第三方（"发给张三""发给某个群"）：不锚定当前会话，session 绑定回答不了，应查通讯录/记录或直接问用户。
- 桥的 session 映射含多个用户且当前请求不带可区分 envelope：绑定来源歧义，需先消歧而非任取一条。
- 需要的是群 chat_id 而非私聊用户 open_id：用户级绑定不适用，应查群配置或消息上下文。
- 发送工具原生默认回发当前会话：连身份解析都可省略，直接调用一次即可验证。
