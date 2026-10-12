---
method_id: symptom-signature-first-incident-triage-e6bc930a2b31
name: symptom-signature-first-incident-triage
description: 面对用户口头报告的服务异常（闪退/卡死/没反应），先用可机械核对的“签名”（退出信号/退出码、错误类型、HTTP 状态）验证报告本身，再决定取证方向；进入某一类证据前，先核对该类 artifact 的 schema 是否可能携带下一个未知量所需的字段。签名不符或字段不存在时，改变证据轴或向用户提最小分区问题，而不是在同一证据类里扩大枚举。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:1853:c376d0b8a1bbb22b3234
evidence_refs: learning:learn:10db9d866bc6
created_at: 2026-09-18T07:26:24.987513+00:00
updated_at: 2026-09-18T07:26:24.987513+00:00
---
## Trigger
用户以模糊症状描述故障（如“刚换模型就闪退”），且系统内存在可机械核对的日志/状态 artifact，故障链有多种可能。

## Discriminator
当时已可见的两条事实：(1) 退出记录全是 SIGTERM（重启信号）而非崩溃，说明报告词“闪退”未必指进程崩溃；(2) 异常记录 schema 只有 phase/error_type/error_message，不含目标 host/port，而当前未知量恰恰是“被拒的是哪个地址”——该证据类结构上无法回答这个未知量。

## Short path
- 读服务/进程状态与异常记录：确认进程是否存活、退出是信号还是崩溃、错误类别（Connection refused=TCP 层被拒，区别于 401/鉴权失败）。
- 做证据能力核对：按该 artifact 的字段集判断下一个未知量（目标地址、精确时间）是否可能出现；不可能出现就记下证据上限，不扩大同类枚举。
- 用现有时间锚点（重启 generation 起始行/时间）把异常切片到本次窗口，区分“本次独有”与“历史常态”，避免把常态噪声当成根因。
- 若仍缺一个只有用户知道的判别量（具体操作路径、现象形态），直接问最小分区问题；同时并行处理已独立核实、无需授权的缺陷。
- 输出时把“已核实事实（带证据位置）”与“未证实假设”分开，并给出可立即执行的下一步。

## Stop conditions
- 症状已映射到具体签名，并排除或确认进程崩溃
- 已从与错误类型一致的证据面得出根因，或明确标注出证据上限
- 所需判别量只能由用户提供时，提出最小分区问题后停止取证

## Verification
- 结论中每条事实都能指向具体 artifact 的行号或字段
- “本次窗口独有”的判断基于时间锚点（重启行号/generation 时间），而非全文件计数
- 事实与假设显式分离，未证实部分给出待验证问题

## Counterexamples
- 症状有单一明确签名且 artifact 直接给出根因（如启动即抛带栈的配置缺失）——直接修，不做证据轴选择
- 故障链唯一且用户操作路径已知——无需分区提问，直接核对该链路
- 疑似安全/数据损坏事件——必须保留完整取证链，最小提问会破坏证据完整性
