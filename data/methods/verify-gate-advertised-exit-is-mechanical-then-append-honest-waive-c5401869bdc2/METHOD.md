---
method_id: verify-gate-advertised-exit-is-mechanical-then-append-honest-waive-c5401869bdc2
name: verify-gate-advertised-exit-is-mechanical-then-append-honest-waive
description: 硬门（收口校验/状态机）拒绝时，错误消息里常写『或请人工确认 waive』类出口，但该出口可能只存在于消息文本，没有任何工具参数或状态转移边实现。方法：先读门与状态机的当前源码（路径以本轮文件系统回执为准，不用上轮记忆路径），拿到确切检查谓词和合法转移表；再全域 grep 出口关键词，区分机械通道 vs 文本出口。若确认仅文本且用户已显式授权，则按 store 自身 append-only 格式追加一行 last-wins 新行：只改谓词命中的字段，不利字段如实保留（不伪造 verified），写入授权时间戳；最后用被绕过门的系统自身代码复验（非自写脚本等价物），通过后再收口，并如实上报手写通道这一事实。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:1482:9cc3986c66ad2e15f746
evidence_refs: learning:learn:bfceef0b3296
created_at: 2026-10-15T08:31:07.624153+08:00
updated_at: 2026-10-15T08:31:07.624153+08:00
---
## Trigger
程序强制的门/状态机拒绝了操作，其错误消息广告了『人工确认/请人 waive/manual override』类出口，而任务需要在用户已授权下让 durable 记录（append-only 账本）通过该门（例：cancelled 任务残留 evidence_required 阻塞收口）。

## Discriminator
在强制代码全域 grep 出口关键词并读门实现源码：若该词只出现在消息字符串/注释里，不出现在任何工具参数、状态转移表或分支条件中（例：cancelled 是无出边的终态、证据校验只挂在 →done 分支），则出口是文本出口而非机械通道；同时门实际检查的谓词（例：evidence_required 且 verification_status!=verified）已可从源码直接读出，无需猜测。

## Short path
- 读门/状态机的当前源码（路径以本轮回执为准），提取合法转移表、门检查的确切谓词、被检查字段
- 在强制代码全域 grep 出口关键词，区分机械通道（工具参数/转移边/分支）与仅消息文本
- 若存在机械通道：直接调用它，不手写账本；若仅文本且用户已有可引用的显式授权：按 store 自身格式 append 一行 last-wins 新行，只改谓词相关字段，不利字段如实保留，并记录授权时间戳与来源
- 用系统自己的门/校验代码复验（非自写脚本），回执 ready 后才执行收口动作，并如实上报手写通道与遗留项

## Stop conditions
- 门代码复验通过（如 unverified 为空、open 任务为 0 / completion_ready=True）且收口回执成功
- grep 命中真实机械通道（工具参数或合法转移边）——停止手写方案，改走该通道
- 用户无可引用的显式授权——停止落账，先向用户求证，不得自免

## Verification
- 账本 append-only：行数只增，历史行内容不变（前 N 行逐字节未动）
- 新行不伪造验证状态（不利字段保持真实值，如 not_checked 不改成 verified）
- 复验调用被绕过门的同一份系统代码而非自写等价脚本，回执含具体 goal/记录 ID

## Counterexamples
- 出口词命中真实工具参数或合法转移边（如 task_update 原生支持 waive 参数）——直接调用即可，手写账本是绕路且可能违反 schema
- store 有 schema 校验器或存在并发外部写者，手写行会被拒或产生竞态——应走管理接口/演进提案而非手写
- 门谓词还检查其他字段（如归档声明、依赖集、自报证据）——只翻一个字段不足以过门，须逐门满足后再收口
- 用户未给出显式授权（无可引用原话/时间戳）——任何情形都不得代为 waive，需先求证
