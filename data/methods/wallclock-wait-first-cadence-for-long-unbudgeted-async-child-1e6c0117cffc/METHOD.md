---
method_id: wallclock-wait-first-cadence-for-long-unbudgeted-async-child-1e6c0117cffc
name: wallclock-wait-first-cadence-for-long-unbudgeted-async-child
description: 派发异步子代理后需等终态，且任务书未定义轮询预算、但可预测child为长任务（自设max_rounds达几十轮、同类child实测十几轮/分钟级）时，不要密集subagent_result自旋：第一跳就用墙钟wait（如120s）做主间隔，subagent_result只作终态探测；任一动作首次触发repeat_guard即把已核事实写入task_state账本一次再继续，不等第二次提醒。与『任务书显式给出wait参数＋次数上限』时的阻塞轮询预算纪律互补，不替代。
aliases: 派出去的子代理多久查一次, 等子代理别一直刷查询, 长任务子代理等待节奏, 轮询自旋怎么破, 等待被repeat_guard提醒后先记账
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fdbebef2-d5fd-4bbb-aa9a-36ef1acf0768:0:b2646b87577d1cca14ff
evidence_refs: learning:learn:4e8a6f6a778c
created_at: 2026-11-09T02:48:17.192116+08:00
updated_at: 2026-11-09T02:48:17.192116+08:00
---
## Trigger
spawn_subagent后需等待终态：子代理任务书自设max_rounds较大（几十轮）或同类子代理已知为多轮/分钟级长任务，且本轮任务书未定义轮询等待参数与次数上限

## Discriminator
第一次轮询前已知的可预测长运行证据：自己写入spawn的max_rounds（如45）、spawn回执给出的wait_seconds=0..30探测口径、既往同类审查child的多轮运行史——足以判定密集同参轮询无信息增益，只会累积repeat_guard计数

## Short path
- spawn后第一跳直接wait(墙钟切片≈预期剩余时长的合理单位，如120s)，未知量=child是否已结算
- wait返回后subagent_result探测终态一次；running则回到wait，不连发同参轮询
- 任一动作首次触发repeat_guard：立即把已核事实/未决/下一步写task_state账本一次，然后恢复wait节奏（不要等第二次guard才记账）
- child到达终态后按终答核验收尾产物（回执文件与终答一致性），退出等待循环

## Stop conditions
- subagent_result返回终态（completed/failed/cancelled）即停止等待循环
- 已按repeat_guard提示记账本一次后，不为同一事实重复记账
- 任务书显式定义了等待参数＋次数上限预算时，本卡不适用，改按该预算的阻塞轮询纪律执行

## Verification
- 整个等待期同参subagent_result连发不超过2次，未出现第二次repeat_guard
- child终态、轮数与终答同后续核验的回执内容一致，等待期未引入额外状态漂移

## Counterexamples
- 子代理预期秒级完成（只读快查类）：墙钟等待反而增加延迟，密集短轮询合理
- 任务书已定义『等待参数＋次数上限』轮询预算：应把每次subagent_result当消耗预算的阻塞等待计数，无需墙钟切片
- child有租约上限或需中途agent_message纠偏：需要更密观测窗，不能一刀切120s间隔
- 环境无独立wait工具时：用subagent_result自带wait_seconds上限作阻塞间隔，机制等价
