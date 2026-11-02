---
method_id: guard-refusal-on-stable-request-property-reroute-never-retry-b7ec50131152
name: guard-refusal-on-stable-request-property-reroute-never-retry
description: 工具护栏返回越权/范围类拒绝，且 reason 归因于请求自身的稳定属性（如『root 位于敏感目录，禁止搜索』）时，这是确定性路由约束，不是可重试错误：首次拒绝后立即按拒绝文案划分被封动词与未封动词，改用精确路径 read/stat 或同一 artifact 的非禁区副本（用户回执中 cp 命令可见的源路径）满足同一未知量；绝不向同一 root 重发同签名搜索。本集 3 次同签名越权拒绝中有 2 次是纯浪费，且第 3 次发生在已成功换通道之后。
aliases: 搜索被安全护栏拦了怎么继续, 越权拒绝换通道不要重试, 封搜索不封read_file, 同一root重复被拒, 用cp源路径副本做核验
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e96054d1-d0eb-4746-93ca-d1f9d169b214:117:b26fb1f7e86c6a9be1e2
evidence_refs: learning:learn:d13c8311fd3a
created_at: 2026-11-01T13:05:12.683885+08:00
updated_at: 2026-11-01T13:05:12.683885+08:00
---
## Trigger
只读核验/检索任务中，工具返回越权或范围类拒绝，且 reason 点名请求的稳定属性（root/scope 位于受限区）与被封的具体动词（搜索），而非缺失字段或瞬时故障；目标 artifact 在用户回执或任务上下文中另有非受限副本路径

## Discriminator
拒绝文案本身就是路由表：它声明了『哪个动词+哪个 anchor』被封（搜索+敏感 root）。若目标本身落在禁区，改参数重发无解；若只封搜索这一动词，精确路径 stat/read_file 未被点名，且用户 cp 命令里可见的源路径（非受限镜像侧）持有同一文件的副本——这些都可在第一次拒绝后立即使用，无需第二次试探

## Short path
- 第一次越权拒绝即停：reason 已声明失败由 root 位置这一稳定属性决定，同请求重发零信息增量
- 按拒绝文案划分能力面：被封动词（目录级内容搜索）vs 未封动词（精确路径 stat/read_file），以及同 artifact 的非受限副本（回执中 cp 源路径）
- 需要文件结构证据时先读非受限副本（镜像侧 patch），一次拿到 diff 头完成文件数对账
- 需要逐行核验时用精确路径 read_file 分段直读，不做目录级搜索
- 计数对账（文件数/插入行数/替换处数）吻合后停止，不再回到被封通道试探

## Stop conditions
- 同一未知量已从未封通道取得权威证据（diff 头、逐行内容、计数对账一致）
- 护栏意图是保护内容本身且不存在用户工作流合法暴露的替代通道时：升级询问用户，不构造绕过

## Verification
- 全 run 内同一 root 的同签名越权拒绝只出现一次（无第二次、更无成功后的复发）
- 最终证据来源为精确路径直读，或与用户回执中可见的 cp/源路径一致的副本位置

## Counterexamples
- 拒绝 reason 是命名缺失字段或参数格式错误（合同差分类）：应按 reason 补字段重发原动作，而不是换通道
- root 只需收窄即可移出禁区（仅某子目录受限）：应改 root 重发搜索，而非放弃该动词
- 护栏目的是阻止读取该敏感内容本身、且从副本读取同样违背其意图：不得用『换个地方读』规避，应升级人工裁决
