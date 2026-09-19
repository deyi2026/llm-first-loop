---
method_id: resolve-recipient-from-channel-bridge-state-7f1ea90906d8
name: resolve-recipient-from-channel-bridge-state
description: 当用户要求经当前消息通道（如飞书桥）把产物发给"我"时，接收人身份不是待发现的任务事实，而是通道桥路由状态自身的一部分。应优先读桥的绑定状态（session map/配置）取当前唯一 receive_id，而不是先搜任务 Evidence/records——历史记录可能返回过期或他人的身份，私发文件会错送。产物转换与身份解析是两个独立未知量，各自沿权威来源推进，互不阻塞。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:37:662986a78396b4db47c4
evidence_refs: learning:learn:2c7eafc89ef0
created_at: 2026-09-18T01:55:05.086702+00:00
updated_at: 2026-09-18T01:55:05.086702+00:00
---
## Trigger
用户要求把产物通过当前正在承载对话的消息通道发送给"我"，而发送工具需要显式 receive_id/open_id/chat_id 且该标识当前未知

## Discriminator
请求时刻已存在的事实：用户消息本身经由该消息桥路由（"通过飞书发给我"意味着桥正在投递本会话），因此桥必然维护"发送方↔会话"的绑定数据；这把"接收人是谁"从开放搜索缩为"读取桥的绑定状态并确认唯一映射"

## Short path
- 拆出两个独立未知量：产物文件、接收人标识；各自沿权威来源推进，不互相等待
- 产物：加载对应转换技能（如 md2pdf），严格代入回执中的 python_executable 与 relative_path_base 执行，以退出码和产物文件存在为验证
- 接收人：在桥的运行时数据/配置目录（运行时数据根而非代码目录）grep open_id/ou-/chat_id/receive_id 模式，读取绑定文件，确认当前会话映射唯一
- 用该标识调用发送工具，要求回执包含 message_id 作为受理证据
- 报告产物路径与 message_id，停止

## Stop conditions
- 发送工具回执返回非空 message_id（送达受理已验证）
- 所用 receive_id 来自桥的当前绑定且为唯一映射，与发送通道一致

## Verification
- 发送回执 message_id 非空
- receive_id 来源是桥的实时绑定文件，而非 Evidence/records 中的历史快照
- 产物文件存在且大小非零

## Counterexamples
- 发送工具隐式回复当前会话、无需 receive_id：直接调用即可，任何查找都是多余动作
- 桥绑定文件含多个 open_id（多用户 bot）：唯一性判别失效，需按当前 session id 对齐或向用户确认，不能任取一个
- 本会话 Evidence 中已有用户明确确认过的 receive_id：直接使用更快，无需 grep 配置
- 目标是群聊 chat_id 或发给第三方而非"我"：需用户显式指定，桥的发送方绑定不适用
