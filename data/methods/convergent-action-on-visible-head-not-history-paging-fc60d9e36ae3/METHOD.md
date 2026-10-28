---
method_id: convergent-action-on-visible-head-not-history-paging-fc60d9e36ae3
name: convergent-action-on-visible-head-not-history-paging
description: 控制面全局快照回执在长历史/审计数组（按旧 generation 记录的 lag 列表等）中途截断时，先对『下一个动作真正需要哪些未知量』做充分性检查：若动作本身已由用户决定、且属于把 target 收敛到 desired 身份的幂等型控制调用（restart 绑定 desired generation），而可见头部已含全部绑定参数（全局 desired 身份 + target 清单），则不逐页翻历史尾部、也不发窄化的同名快照重查（同一序列化器常返回同一全局负载）；直接以头部参数发起动作，各 target 的 live 状态改由动作终态收据的 verify 证据权威提供。本集可省去 3 次历史分页、2 次冗余 per-target status、1 次参数契约失败。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:1348:5a0181e1b0a973d96307
evidence_refs: learning:learn:c655b2fc8421
created_at: 2026-10-21T19:43:00.576799+08:00
updated_at: 2026-10-21T19:43:00.576799+08:00
---
## Trigger
待执行的控制面状态变更（重启/发布类）已由用户或上游决定；控制面 status 全局快照回执在历史/审计数组内被截断，各 target 运行详情块落在不可见尾部

## Discriminator
截断点位于带旧 generation 键的历史数组内（条目 generation 远小于当前 desired），即可判定隐藏尾部是历史而非 live 状态；同时可见头部已给出动作所需的全部参数：全局 desired 身份（generation/git_head/deployment_id）与剩余 target 清单。对『绑定 target 到 desired』的收敛型动作，各 target 当前运行块不是前置未知量——事后终态收据的 verify 证据反而更权威

## Short path
- status 全局快照：从可见头部确认 desired 全局身份与已完成 target，并确认截断点落在历史 audit 数组内
- 对下一步动作做未知量枚举：restart 只需 target + expected_generation，均已在头部可见 → 判定隐藏的各 target 运行块非动作前置，停止分页与窄化重查
- restart 字段名未在前文证实时，先 get_tool_schema(service_control) 取参数契约，避免 missing=target 类失败
- 逐 target 发起 restart(target=..., expected_generation=desired)，参数逐字取自快照头部，记录各 action_id
- 有界等待后按 action_id 查询终态；terminal 收据的 verify_evidence（pid/git_head/generation）即为权威的各 target live 事实
- 仅用终态收据汇报并停止，不回头补读快照尾部

## Stop conditions
- 每个 target 均取得 status=succeeded 终态且 verify_verdict=confirmed_ok、generation 与快照头部 desired 一致
- 出现 failed 终态 → 转入 verify_acknowledge/修复分支，不再补历史
- 仅当某参数既为动作必需、又只存在于被截断段时，才定点恢复该段（窄区间读或 event_stream），而非全量分页

## Verification
- 各 target 终态收据 deployment_generation == 头部 desired，pid 与 git_head 双确认
- 最终结论只引用终态收据/verify 证据，不把历史 lag 条目当作当前状态
- 窄化重查若返回与先前相同的 blob/前缀（同一全局序列化），立即终止该查询分支

## Counterexamples
- 动作非收敛/非幂等：重启会中断在途工作、或不同 target 需按当前运行状态区别处理 → 各 target 当前运行块就是前置未知量，必须先取到再动
- admission_barriers 非空，或历史数组近端 generation 存在失败/异常条目 → 历史本身影响决策，须先读近端再决定
- 回执未截断或体量小 → 直接读全即可，无需充分性捷径
- desired 身份本身位于被截断尾部 → 不能凭旧值/记忆行动，必须先定点恢复该身份
