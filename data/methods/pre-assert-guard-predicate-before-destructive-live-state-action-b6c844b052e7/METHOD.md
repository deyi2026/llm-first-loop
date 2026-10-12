---
method_id: pre-assert-guard-predicate-before-destructive-live-state-action-b6c844b052e7
name: pre-assert-guard-predicate-before-destructive-live-state-action
description: 对活跃 UI/文档执行不可逆覆盖性操作（粘贴、删除、替换、提交）前，先当场读取并断言一个可机械查询的守卫谓词（如 getSelection().toString().length===0），再派发动作。谓词不满足时，在与消费 API 相同的粒度上修复状态——本集是把折叠光标锚进段落文本节点内部（setStart(node,0)）而非段落边界（setStartBefore）——修复后重新断言，仍不安全则中止而非带病执行。动作后立即跑内容守门（chars/paras/媒体加载计数），要求 delta 恰等于预期新增，把『页面上完全静默、只表现为字数归零』的破坏变成派发前可拦、派发后可检出的硬失败。核心转变：从『我设置过状态』改为『我读过状态』。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:fe0e1465-7509-459e-8792-eaaf6d7269f5:313:e55f2b180a97b3ea97ba
evidence_refs: learning:learn:1258617da3b4
created_at: 2026-10-11T21:56:10.541911+08:00
updated_at: 2026-10-11T21:56:10.541911+08:00
---
## Trigger
即将对活跃 UI/文档/共享状态执行不可逆或覆盖性操作（粘贴、删除、替换、提交），此前只设置过相关状态（range/光标/表单值）但从未验证其当前实际取值，且失败模式在界面上完全静默（无报错，只表现为内容丢失或被顶掉）。

## Discriminator
破坏性操作的成败取决于一个当时即可查询的运行时事实：实际选区状态。本集中 getSelection().toString() 的长度在任何时刻都可读，却直到用户纠正（『文字还是全选状态，一粘就覆盖』）后才被首次断言。这个谓词的当前值能把『盲目派发后枚举失败原因』缩成一次确定性的闸门检查，属于 knowledge-at-time 内可用的判别事实。

## Short path
- 派发破坏性动作前，先读守卫谓词当前值（未知量：真实选区/状态是否处于安全态，而非我是否设置过它）
- 若不安全：在与消费 API 相同粒度上修复状态——折叠 range 时锚定在目标段落文本节点内部（setStart(node,0)/setEnd(node,0)），而非段落元素边界（setStartBefore/setEndBefore）；粒度选错会让断言通过而行为仍错
- 紧贴派发动作之前重新断言谓词；仍不满足则中止并显式报告，不静默覆盖
- 派发后立即核对内容守门指标（chars/paras/媒体加载计数），确认 delta 恰为预期新增（本集：chars 3434→3438 仅 +4 图块文本、paras 73→76、real_imgs/loaded 全部到位、正文字数不变）

## Stop conditions
- 守门指标显示原内容完整保留且新增仅为预期 → 动作成功，停止重试
- 谓词修复失败或断言不过 → 中止派发并报告，绝不带病执行覆盖

## Verification
- 断言与派发之间不得插入其他会改变该状态的操作（assert→dispatch 原子相邻），否则断言失效（TOCTOU）
- 动作后 chars/paras 的 delta 必须能逐项解释；字符数回落或图计数缺失即判为静默覆盖，视为失败
- 迁移前核对动作语义：本应替换选区的操作不适用空选区断言

## Counterexamples
- 操作语义本身就是替换当前选区（刻意覆盖式粘贴、replace 命令）：要求空选区会阻止正确行为
- 破坏性动作没有可查询的前置状态（fire-and-forget API、服务端立即消费）：应改用 dry-run、沙箱副本或事务回滚，而非硬造一个无意义断言
- 断言之后、派发之前还有其他步骤会改动该状态（TOCTOU）：此时断言只是仪式，必须把断言与派发合并为相邻原子步骤，或改用不可变快照句柄
