---
method_id: bounded-blocking-wait-over-busy-repoll-b706e228900c
name: bounded-blocking-wait-over-busy-repoll
description: 后台子代理/异步任务处于 running 态、需要回收终态时，若工具回执已文档化阻塞等待参数（如 wait_seconds=0..30）并提示『可继续父级工作』，则每次回收调用应携带最大等待值或在间隙做父级独立工作；对完全相同的 pending 回执反复同形重发不产生新信息（本集 15 次 identical running 轮询即此摩擦）。配套纪律：终态文本若中段截断，必须沿 recovery_ref 分页取回 complete=true 并核对 blob SHA 后才逐字转录，不得用摘要代替原文。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25393690-39c2-43d8-b50f-3157a58aaea2:74:41d137b1d11eacb31240
evidence_refs: learning:learn:c0f32dd7265c
created_at: 2026-10-15T01:54:22.992988+08:00
updated_at: 2026-10-15T01:54:22.992988+08:00
---
## Trigger
已 spawn/启动后台异步执行体（子代理、长任务）并需回收其终态；工具回执显式给出阻塞等待范围（wait_seconds 等）与『稍后查询/可继续父级工作』提示；或回收到的终态文本带截断标记（omitted/中段截断）而任务要求逐字留存。

## Discriminator
spawn 回执在首次轮询前已可见的两条事实：一是文档化的最大阻塞等待值（wait_seconds=0..30），二是『可继续父级工作、agent_message steer』的显式建议——说明每次调用可以满载等待或置换为独立工作，而不是在收到与上次完全相同的 running 回执后立即原样重发。

## Short path
- spawn 后记录 child_id 与身份闸期望值（SHA/字节数/文件数），首次回收即用 wait_seconds=文档最大值阻塞等待
- 仅当等待窗口被完整耗尽且仍 running 才再次查询；间隙做父级独立准备（回执头部骨架、复检命令预演），不介入被审工作
- 终态若含截断/omitted：立即沿 recovery_ref 分页 hydration 直到 complete=true，核对每页 range SHA 与整体 blob SHA 一致
- 将 child 终态逐字转录到新产物（附 child_id、差异 SHA、完整性锚），不覆盖旧兄弟产物
- 落盘后重验不变量：权威面（staged diff 字节/SHA/文件数）未变、旧产物哈希未动、新产物处于预期跟踪状态，再宣称完成

## Stop conditions
- child_state 变为 completed/failed/cancelled 且回收文本完整（complete=true 或无截断标记）
- pending 回执发生质性变化，改按新信息分支
- 等待总预算耗尽且无进展，升级为 steer/cancel/求助而非继续同形轮询

## Verification
- 相同 running 回执的调用次数 ≈ ceil(实际等待/最大 wait 值)，不存在等待窗口未耗尽的重复调用
- 转录产物与 recovery blob 逐字一致（哈希锚定），截断标记零残留
- 终局声明前的复检输出与 spawn 时记录的身份闸期望一致

## Counterexamples
- 子代理已知可能需要中途 agent_message 纠偏且阻塞等待会掩盖 steer 时机时，长盲等反而延迟干预，应缩短等待或穿插检查
- 工具无阻塞等待参数（纯状态端点轮询是唯一手段）时，本方法触发条件不成立
- pending 回执携带新进度信息时，每次调用都在获取新信息，不属于零信息重复，不应强行拉长间隔
