---
method_id: prove-non-delivery-via-commit-ledger-and-closed-target-error-3b5a4be98aea
name: prove-non-delivery-via-commit-ledger-and-closed-target-error
description: 当被问/担心'重复派发是否真的到达外部服务、有没有造成扰动'时，用事件账本的成交标记（如 exchange_committed）计数作为送达真值：失败 attempt 只有 opened/settled 而无成交事件、且 error_type 为闭合目标类（TargetClosedError，毫秒级、open 阶段）即可证明载荷未发出。closed-target 错误同时指向本地陈旧句柄，处置是重建 surface 而非重试载荷。顺序：先停发、再数账、再按 error_type 分类；'句柄无自愈'等机制确认等修复路径获批后再读代码，避免在问题已可回答时扩入全文件源码枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8bc1cbb3-5fe5-44cb-9818-3acb329d2acb:359:b1d67a1ee228918ae84e
evidence_refs: learning:learn:5848b81ea195
created_at: 2026-10-11T17:46:19.017418+08:00
updated_at: 2026-10-11T17:46:19.017418+08:00
---
## Trigger
用户担心重复/失败的派发可能已实际到达外部服务（重复发送、扰动、风控/计费风险），问'到底发出去了几次/失败原因'；系统存在可区分成交事件（exchange_committed 类）与传输层 opened/settled 错误事件的 provider 事件账本，且失败带结构化 error_type。

## Discriminator
失败 attempt 只有 transport opened/settled、无任何成交事件，且 error_type 为闭合目标类（如 TargetClosedError）、毫秒级、发生在 pcall open 阶段 ⇒ 载荷确定未离开本进程，非送达可证；该 error_type 同时指向本地陈旧 page/连接句柄而非远端或协议故障，故正确处置是重建 surface（重启/重连），不是重试同一载荷。

## Short path
- 用户表达发送顾虑时先冻结一切派发，再取证
- 读失败 attempt 的 settled 错误明细，取 error_type 与发生阶段——回答'失败原因'
- 对整个关注时间窗读 provider 事件账本，只数成交事件——回答'实际送达几次'，避免用单个小窗口以偏概全
- 由'成交数=0 + closed-target/open 阶段错误'给出非送达结论；'句柄无自愈'等机制判断标注为行为证据支持的推断（两次同类毫秒级 open 失败），代码级确认留到用户批准修复路径之后
- 输出计数表+堵点+待决选项后停止，不继续扩入全文件源码枚举

## Stop conditions
- 账本窗口已覆盖全部待核查派发，且每个非成交失败都有明确 error_type 分类
- 关注窗内出现计划外的成交事件 ⇒ 结论翻转为'确有重复送达'，立即上报而不是继续排查

## Verification
- 报告的送达次数 = 账本中成交事件的计数（可复算），不是由意图或记忆推断
- 每条失败原因都引用具体 error_type 与发生阶段（open 阶段 vs 发送后）
- 任何'无自愈/需重启'断言要么引用重复同类 open 失败的行为证据，要么引用具体代码行，至少其一

## Counterexamples
- 错误发生在发送之后（timeout/5xx/解析失败）：载荷可能已到达远端，禁止宣称非送达，需以远端侧确认或账本成交事件为准
- 系统没有事件账本或不区分成交与传输事件：此判别不可用，需先补埋点或换证据源
- 用户要的是'修好 transport'而非'影响评估'：读代码/复现就是第一路径，此时跳过代码反而是绕路
