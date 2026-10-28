---
method_id: rejection-reason-as-contract-diff-reissue-on-named-dimension-ec5de70cbb1c
name: rejection-reason-as-contract-diff-reissue-on-named-dimension
description: 准入/前置校验类工具返回 accepted:false 且 reason 是命名缺失字段的自描述错误码时，该 reason 就是本次调用与合同的差分：先机械翻译成『拟补字段=取值』（取值优先来自任务上下文已知事实，如发布目标平台名），再重发一次且仅一次、只在该维度上不同的调用；禁止无差异原样重试。本集两次同参重发 publication_target_name_required、外加一次 60s 超时后才 grep 源码定位 raise 行，而字段取值（今日头条）当时早已在任务上下文中。源码定点阅读只留给 reason 不自描述、或补字段后返回全新 reason 的情况；且无 raise 位置源码证据时，不得把『缺字段拒绝』叙述成『白名单不覆盖目标』。
aliases: 返回缺字段就补上重发一次, 别拿同样参数再发一遍, reason 指名缺哪个字段, target_name_required, 接口说缺个参数, 被拒理由就是待办
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:7258b3db-ea07-41d6-9ce6-9d285e331be0:148:21d24a6d845f1ac3b61f
evidence_refs: learning:learn:635fa02b926e
created_at: 2026-10-20T08:35:28.901364+08:00
updated_at: 2026-10-23T05:52:05.741453+08:00
---
## Trigger
结构化准入/前置校验调用（admission、gate、contract check）返回 accepted:false，且 reason 为命名缺失字段或命名违约维度的自描述机器可读码（如 <field>_required、missing <field>）

## Discriminator
reason 命名的维度在该时刻是否已有可推导取值：本集 reason=publication_target_name_required，而发布目标平台是任务早已确定的事实——两者同时成立，即可不依赖任何新信息直接构造下一次不同的调用

## Short path
- 首次拒绝后先做机械翻译：reason → 拟补字段=拟取值，取值取自任务上下文已知事实（目标平台名、目标 id 等），不发起任何新探索
- 重发一次且仅一次、参数 diff 恰为该命名维度的调用；不得原样重试
- 若返回语义上全新的 reason：以新 reason 为下一个未知量重复上两步；若 reason 不自描述（无字段名或取值不可推导），才用错误串定点 grep raise 位置，读字段语义与合法取值域
- 若确认工具接口根本未暴露该字段：停止重试，把『接口与合同不匹配』作为缺陷记录，并选择带回执留痕的显式偏离路径
- 准入通过≠物理拦阻：实际执行若走 gate 适配器之外的路径（如直连 CDP），将该偏差显式写入发布回执而非默认已过闸

## Stop conditions
- reason 命名维度已补齐且调用被接受，或返回语义上全新的 reason（按其继续迭代）
- reason 不自描述且定点源码阅读已给出字段语义与合法取值域
- 确认接口无法表达该字段，缺陷已记录且偏离路径已留痕

## Verification
- 对照两次调用的参数 diff：应恰好等于 reason 命名维度，无其他变动
- 最终叙述与回执一致：把『缺字段拒绝』改述为『白名单/能力不覆盖』之前，必须有 raise 位置的源码证据
- 重发前确认该调用是纯校验（幂等）；对可能已有副作用的动作先取权威完成证据再决定

## Counterexamples
- reason 为不透明码（internal_error、generic invalid_request，不含字段名）→ 定点 grep 源码/日志才是正确下一跳，本方法不适用
- 命名字段的取值不在任务上下文中（外部 tenant_id、服务端生成的 id）→ 第一未知量是取值来源，盲填重发无意义
- 被拒动作幂等性未知且可能已产生部分副作用（发文、下单）→ 先读权威完成台账再决定是否重发，而非直接改参重试
