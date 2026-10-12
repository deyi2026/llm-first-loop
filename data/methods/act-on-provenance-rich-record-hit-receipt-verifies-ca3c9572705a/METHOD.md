---
method_id: act-on-provenance-rich-record-hit-receipt-verifies-ca3c9572705a
name: act-on-provenance-rich-record-hit-receipt-verifies
description: 动作缺一个参数（收件人ID/端点/绑定别名）时先定向检索 records/memory：若命中同时携带①值的确切存储来源(provenance) ②唯一/当前绑定标记 ③曾用同一工具+同类负载成功的先例，且该动作失败可观察、重试廉价，则直接以该值执行动作，把动作回执(message_id/成功码)当作参数验证，不再回读底层配置文件二次确认。仅当记录跨越该事实的可能变更窗口、动作不可逆或高爆炸半径、或失败静默时才预核实时源；预核时被引用的运行态相对路径(data/)应按 runtime_root 解析而非代码 worktree。收益：把'记录+源文件双验'缩为'记录→动作→回执'单链，省一至两个确认轮。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:242:7e7694b130d513f55e0f
evidence_refs: learning:learn:87e508030fa8
created_at: 2026-09-18T02:19:49.420391+00:00
updated_at: 2026-09-18T02:19:49.420391+00:00
---
## Trigger
需要执行一个外部动作（发附件/调用服务/通知），但缺少一个可检索的参数值（如 receive_id、endpoint、绑定的别名），且该动作本身会产生可观察的成功/失败回执

## Discriminator
检索命中是否同时含三要素：值的确切存储来源（写明配置于哪个文件）、'当前/唯一绑定'类标记、'曾用同一工具同类负载成功'的先例；且目标动作失败会明确报错（如 receiver 不存在即报错），重试代价低。本例命中首条即同时写明配置文件位置、唯一私聊绑定、曾用同一发送工具成功发过同类报告附件，三要素齐备

## Short path
- 定位当前子任务缺失的唯一未知量（如发送所需的 receive_id），用 records/memory 定向检索该量，不做宽枚举
- 命中带 provenance+唯一绑定+同工具成功先例三要素 → 直接以该值调用动作工具
- 以动作回执验证参数：success 回执（含 message_id/成功码）即完成验证，转入下一子任务
- 仅当回执报参数类错误（receiver 不存在等）才回退读实时绑定源，重取值重试一次
- 若确需预核实时源：其 data/ 运行态相对路径按 runtime_root 解析（运行态数据不在代码 worktree 下），避免先猜错基路径再 find 兜底

## Stop conditions
- 动作回执成功且带标识（message_id/成功码）后，不再对同一参数做二次来源确认
- 用户所需的各子任务（生成/发送/起草）均已有成功回执或落盘产物后停止，不追加'再确认几个'类动作

## Verification
- 动作回执为 success 且带唯一标识，无 receiver/param 类错误，即认定参数正确
- 若跳过预核后动作失败：回退读实时绑定源应能解释差异（值已变更），纠正后重试成功，说明回执作为验证器闭环有效

## Counterexamples
- 记录时间跨过该事实的可能变更窗口（绑定支持多用户、近期有换绑操作）→ 回执验证不再是廉价保险，必须先读实时源
- 动作不可逆或误发即造成泄露/高爆炸半径（敏感收件人、群发、删除类）→ 不能靠'失败再重试'兜底，必须预核
- 动作无回执或失败静默（fire-and-forget）→ 回执无法充当验证器，本方法不适用
- 命中只有裸值、无 provenance 与成功先例标记 → 不满足判别条件，需先溯源再决定是否直接行动
