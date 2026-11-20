---
method_id: async-child-first-touch-is-sized-wait-not-instant-poll-26cf8fd9f3ae
name: async-child-first-touch-is-sized-wait-not-instant-poll
description: 受管入口成功启动异步子代理（独立 Reviewer/评测/盲评等）且回执无错误后，第一动作不是立即查询子代理状态：此刻距启动≈0，而此类审查的最短可信完成时间以分钟计，即时查询几乎必然得到非终态'尚未结算'，只是复述启动回执已含的信息，浪费一次调用。改为直接发起一次时长≥估计最短可信完成时间的阻塞等待（按任务规模与同类先例定档），到期后查询一次；非终态则按回执自带的'可稍后查询'提示继续定时等待，不做连续短间隔轮询。拿到终态结构化裁决后立即履行下游义务并停止。
aliases: 子代理刚启动要不要马上查, 异步审查等多久再查结果, 刚 spawn 的 reviewer 立刻查是不是浪费, 受管审查启动后的第一动作, 避免多余的子代理状态查询
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b81d97a3-af1f-463a-9f1f-ac9cf885c32b:590:a7f453dc59918448b3e5
evidence_refs: learning:learn:0c54d58a686e
created_at: 2026-11-17T09:27:59.728888+08:00
updated_at: 2026-11-17T09:27:59.728888+08:00
---
## Trigger
受管/受控入口（merge_review_start 类）成功启动全新异步子代理，回执给出 child_id 且无任何失败信号，且任务书规模表明最短可信完成时间远大于已流逝时间时，规划启动后的下一个动作。

## Discriminator
启动回执已确认'已启动/running'且无错误码；此刻 elapsed≈0；该子代理的任务量（数百行代码审查、多轮工具、需结构化裁决）决定终态不可能在秒级出现——t≈0 的状态查询信息增益≈0，只会重放回执已含事实。

## Short path
- 受管入口启动子代理后先核对启动回执：启动成功、child_id 在手、无失败信号；唯一未知量=何时到达终态
- 不发起 t≈0 状态查询，直接发起一次带时长的阻塞等待，时长取估计最短可信完成时间（代码审查类取分钟量级，可参照同类子代理先例）
- 等待到期后查询一次：终态→核对结构化裁决字段（verdict/p0/p1/SHA 回显）与任务书锚定值一致，立即做下游义务（checkpoint/入档）并停止
- 非终态→按回执提示与剩余估计时长再等待一轮，不连续短间隔轮询
- 任何时刻出现失败/cancel/steer 信号→转为按信号处置，退出纯等待分支

## Stop conditions
- 查询返回终态且结构化裁决与任务书锚定值一致→履行下游义务后停止轮询
- 启动回执即报错或缺 child_id→报告准确阻断并停止，不进入等待
- 等待中出现失败/cancel 信号→按信号处置，不再盲等

## Verification
- 终态回执为结构化 JSON 且关键字段（verdict、p0/p1、child_id、base/head SHA）与任务书逐一对上
- 调用数对账：成功启动的子代理收口，状态查询类调用≤阻塞等待次数+1（压缩后路径为 start→wait→poll→checkpoint，无 t≈0 冗余查询）

## Counterexamples
- 启动回执缺失 child_id/状态或带错误告警→子代理可能瞬时死亡（spawn 即预算耗尽/provider 校验失败），此时立即核实是正当的，本方法不适用
- 任务书自带轮询协议或预算（等待参数+次数上限）→按任务书与既有预算计数方法执行，不套用默认等待档
- 子代理任务本身可在亚分钟完成（单轮、纯回显/格式化）→短间隔甚至立即查询合理
- 需要在启动后尽早 steer 或取消（发现启动错目标/错模型）→立即查询以获得 agent_message 通道与最新状态是正当的
