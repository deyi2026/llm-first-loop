---
method_id: write-precondition-token-before-first-edit-ad1f203fa6ef
name: write-precondition-token-before-first-edit
description: 在编辑工具带版本化写前置条件（file_contract / expected_snapshot_ref 类乐观锁）的环境里，对已存在文件的首次编辑前，先通过一次 snapshot 读取取得写前令牌：把「内容理解」与「令牌获取」合并为同一次 read(snapshot=true)，再携带令牌编辑。普通内容读取不产生令牌；契约失败回执虽会给出 required_call/retry_field 补救配方，但事后补救要多付一次失败编辑加一次重复读取。每次成功写入后记录新的 artifact/snapshot 引用供同文件后续编辑复用；期间若发生写入则令牌作废，需重取后再试。
aliases: 改文件前先拿写令牌, 一次读取同时取快照引用, 写被拒后别原样重试, file_contract 乐观锁回执, 手里没有版本号
status: qualified
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:329:cbbdfff9ac89d3f9d02a
evidence_refs: learning:learn:e7867fdfc122
created_at: 2026-09-21T02:50:32.140021+00:00
updated_at: 2026-10-30T10:48:34.835412+08:00
---
## Trigger
会话内即将首次编辑某个已存在的文件，且所在环境的 edit 工具实施版本化写前置条件（如 expected_snapshot_ref / etag / If-Match 类契约）

## Discriminator
手中没有该目标文件路径的新鲜写前令牌——此前 read_file 的输出里不含任何 snapshot_ref（普通读只回内容不回令牌）。这个可观察的缺失本身即判定：必须先做 snapshot 读，直接编辑必然触发契约拒绝

## Short path
- 确定要修改的目标文件与编辑意图；未知量：是否已持有该文件的有效写前令牌
- 检查环境 edit 契约且发现无令牌：执行 read_file(path, snapshot=true)，一次调用同时满足内容核对与令牌获取
- edit_file 携带 expected_snapshot_ref=<令牌>；未知量：编辑是否被契约接受
- 校验回执 precondition_checked=true 且写后复读与预期变更一致；记录返回的新 artifact/snapshot 引用供同文件后续编辑复用
- 若前置条件失败（说明快照后有 intervening 写入）：重新 snapshot 取新令牌后重试一次，绝不无令牌盲试或原令牌重放

## Stop conditions
- 编辑回执显示前置条件校验通过（precondition_checked=true）且写后复读与意图变更一致
- 目标为新建文件且该写路径不要求既有版本的前置条件

## Verification
- 回执中 expected_snapshot_ref 与本次实际使用的令牌一致，且 precondition_checked=true
- 写后复读（或哈希）与预期编辑内容一致，即工具侧报告『写后复读一致』
- 同一文件的下一次编辑复用最新引用；一旦出现 precondition 失败回执，立即重取令牌而非重放旧值

## Counterexamples
- 新建此前不存在的文件（无既有版本可比对）时，写路径通常不要求 snapshot 前置，先取令牌是纯开销
- 环境根本没有版本化写契约（edit 不校验前置条件）时，为编辑而额外做 snapshot 读是浪费
- 工具提供整文件全量重写且不校验前置条件的写入口时，直接全量写即可，无需令牌
- 持有的令牌取自任何一次中间写入之前（已陈旧）——此时方法不是复用令牌，而是把『令牌已失效』本身当作重取触发器
