---
method_id: ledger-then-interleave-readonly-prefill-in-long-async-review-wait-6ae624d5f4fc
name: ledger-then-interleave-readonly-prefill-in-long-async-review-wait
description: 异步审查/准入子代理 pending 且 start 回执的 estimated_seconds 远超单次等待上限时，不要纯空转轮询到重复守卫提醒才动：首个 pending 确认后，先把已核事实（含引用/未决/下一步）记入任务账本，再把任务书中与裁决结果无关、严格只读、单段可在窗口内完成的必做核验（如下游门禁脚本副作用预检）前移进等待窗口执行，随后恢复配速轮询。窗口内任何写操作都必须推迟，那会改变被审候选指纹、作废在途审查。
aliases: 等审查结果期间能先做什么, 轮询空窗期插空干活, 子代理长ETA等待不要干等, 审查pending时前移只读预检, 反复wait被判重复之后怎么办
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:837:6bc8605f04811a1638e2
evidence_refs: learning:learn:1d00fafbdb94
created_at: 2026-11-07T18:10:12.638450+08:00
updated_at: 2026-11-07T18:10:12.638450+08:00
---
## Trigger
异步准入/审查子代理已启动并进入 pending；start 回执给出 estimated_seconds/deadline 且远大于单次等待上限；同一任务还存在下游阶段要求的、与裁决结果无关的只读核验，或轮询已触发同调用重复执行提醒

## Discriminator
start 回执里可量化比较的窗口事实：estimated_seconds 除以单次等待上限远大于 1（如预估约二十分钟对单次两分钟上限，约十个纯等待周期），且首个 status 回执确认 pending 并给出剩余秒数，这证明等待窗口是可计划的空余容量，而非常规轮询节奏

## Short path
- 收到 start 回执时记录 estimated_seconds/deadline 与等待上限之比；比值远大于 1 即预留窗口利用计划
- 首个 wait+status 确认 pending 后，先把已核事实+引用+未决+下一步写入任务账本（满足重复守卫的前置要求，保证轮询可无损恢复）
- 挑选与裁决无关、严格只读、单段可在窗口内完成的必做核验（如只读解析下游门禁脚本的副作用范围）逐段执行
- 恢复 wait 配速轮询；终态回执一到立即停止插空，按裁决分流
- 终态非 PASS：读完整报告、checkpoint、停在下游阶段之前；仅真实 PASS 才进入下一阶段

## Stop conditions
- 子代理终态回执（任意 qualification）到达——立即退出插空与轮询，按裁决行动
- 无剩余的裁决无关只读事项——回到纯配速等待，不为填窗口制造凑数工作
- 插空步骤需要写操作、可能触碰被审候选，或预计超出剩余窗口——推迟到终态后

## Verification
- 终态回执的 candidate_sha256 与 start 回执逐字节一致
- 插空期间工作区/冻结材料零变化，被审指纹绑定未破坏
- 账本先于插空写入且含已核事实、引用、未决与下一步
- verdict 与计数取自完整报告文件的机械解析，而非截断尾部推断

## Counterexamples
- 预检内容依赖裁决结果（如需先知道哪些缺陷待修再定范围）——必须等终态后做，前移只会白做或做错
- 插空步骤含任何写操作（哪怕顺手小修）——会改变候选指纹，使在途审查整体作废
- estimated_seconds 与单次等待上限同量级（如 150s 对 120s）——窗口不足，纯配速等待即可
- 没有既定只读待办——不要为利用窗口而发明探索，纯等待是正确行为
