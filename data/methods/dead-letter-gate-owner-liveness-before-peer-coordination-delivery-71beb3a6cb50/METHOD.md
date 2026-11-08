---
method_id: dead-letter-gate-owner-liveness-before-peer-coordination-delivery-71beb3a6cb50
name: dead-letter-gate-owner-liveness-before-peer-coordination-delivery
description: 多会话共享仓中被要求『协调其他会话收敛 lane/goal』时，第一个未知量不是协调话术怎么写，而是每个待收敛对象的 owner 会话是否可触达：协调/收件箱回执里的 owner 最近活动时间戳与消息 pending 停留时长就是现成判据。owner 活跃→只发单一明确请求（ETA 或指定 close 动作）并做一次有界复查；owner 沉默超长窗口且通道为纯拉取（无注入点）→投递即死信，收敛预期按零处理：投递可留痕，但立即并行向用户呈报『路径不存在』（唤醒/授权代理收口二选一），并把机制缺口（唤醒队列、第三方带证据仲裁关闭、收尾 pending 检查）落成演进建议。用一条可证伪事实替换『再催几轮』的枚举。
aliases: 给不在线的会话发消息是不是白发, 协调消息一直没人取怎么办, 催别的会话收口前先看它还活着吗, 沉默会话的 lane 谁来收, 纯拉取收件箱协调不到人, 跨会话死信判断
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:1849:8e35e323bbb344704752
evidence_refs: learning:learn:d847e1a12444
created_at: 2026-11-08T09:34:26.371261+08:00
updated_at: 2026-11-08T09:34:26.371261+08:00
---
## Trigger
任务要求让其他并行会话的 lane/goal/合并队列收敛（协调、催 ETA、催收口），而本会话只能通过落盘收件箱/消息类工具触达对方

## Discriminator
协调回执已含各 owner 的最近活动时间（last checkpoint/last activity）与待处理消息停留时长；owner 最后活动距今超过一个长窗口（如 19h）且消息持续 pending、通道又无注入点（纯拉取式）→继续投递不会产生收敛：这是收件人不存在，不是措辞或频次问题

## Short path
- 一次只读查询把『待收敛对象→owner session→最近活动时间→消息 pending 时长』查全（未知量：谁负责、还活着吗）
- 活跃 owner：只发单一明确请求（ETA 或指定 close 动作），做一次有界复查
- 沉默 owner：投递可留痕但收敛预期按死信处理——并行上报『owner 无 run、消息永不被读』并给用户唤醒/授权代理收口两选项，不代 owner 判定收口
- 若任务假设『应该能协调』而机制只有投递段：把唤醒队列/仲裁关闭/收尾检查缺口落成演进建议后停，不换措辞加码催促

## Stop conditions
- 每条待收敛 lane 都有明确承接：owner 已响应，或用户已裁决唤醒/代理收口
- 不再向无近期活动的会话追加协调消息

## Verification
- 投递后复查收件箱 pending 与 owner 活动 时间戳：均未变即为死信实证
- 机制断言（纯拉取/无注入点、守卫动词覆盖面）须落到源码定义或审计回执，不凭注释或意图推断

## Counterexamples
- owner 会话在线且周期查收（活动新近、消息很快被取走）→正常投递即可，无需升级
- 协调通道是推送式（有唤醒/webhook/注入点）→消息会被送达，沉默窗口不构成上限
- 任务只求通知留痕、不要求对方动作或收敛→死信无害，不必打扰用户裁决
- 同会话内子代理轮询（parent-child）→走轮询预算方法，不适用收件箱死信判断
