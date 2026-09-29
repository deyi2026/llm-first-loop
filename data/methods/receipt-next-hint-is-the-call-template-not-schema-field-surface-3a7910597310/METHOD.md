---
method_id: receipt-next-hint-is-the-call-template-not-schema-field-surface-3a7910597310
name: receipt-next-hint-is-the-call-template-not-schema-field-surface
description: 控制面类工具（发布/重启/生命周期）成功回执常带结构化 next 指引，已显式写出后续调用的 action 与参数名。把它当权威调用模板逐字使用，而不是从工具 schema 字段表面自行拼装——尤其当 schema 存在多个同枚举近义字段（target vs restart_target），其作用域只在 prose 里区分时。参数校验报错若自相矛盾（宣称的允许集已含传入值），说明是字段路由/作用域问题：读一次完整 Schema 修正，不重试值变体；且先验证一个调用的形状被受理，再对剩余目标 fan-out。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:afaf8a78-607b-4e8e-8fd2-0e3cc4e07be4:322:1e6760a654ba46e1334d
evidence_refs: learning:learn:fe02a01cfc8c
created_at: 2026-09-24T13:40:45.884123+00:00
updated_at: 2026-09-24T13:40:45.884123+00:00
---
## Trigger
刚收到含结构化 next/指引字段的成功回执（如 publish 后提示 restart），需紧接着向同一控制面发起后续调用；或工具 schema 有多个同枚举近义参数、其 action 作用域仅靠描述文本区分

## Discriminator
回执 next 字段已显式给出调用的 action 与参数名（如 'action=restart, target=...'），或失败回执宣称的允许集已包含刚才传入的值——后者证明失败源于字段名/作用域而非取值

## Short path
- 读回执：若 next/指引已给出精确调用形状，按其逐字构造首个调用，不凭 schema 字段表面改换字段名
- 若 schema 有同枚举近义字段且回执未给形状：先取一次完整 Schema 再发首个调用
- 首个调用被受理（拿到 action_id/退出码0）后，再对剩余目标 fan-out 同形状调用
- 校验失败且报错允许集已含传入值时：读完整 Schema 定位该 action 的字段作用域，一次修正字段名，禁止换值重试或齐射重发
- 异步动作以 status 查询终态收口，受理不当作完成

## Stop conditions
- 每个目标的调用均拿到受理回执（action_id 或 success），且报错文本不再与传入值自相矛盾
- 异步动作终态（succeeded/failed）经权威 status 查询确认后再宣布

## Verification
- 逐目标核对受理回执中的 action/target/generation 与意图一致
- 若曾出错：修正后的参数名与 schema 中该 action 的字段作用域一致
- 失败回执中的允许集确实覆盖传入值（确认是路由错误而非值错误）

## Counterexamples
- 回执 next 未给参数名、或与当前工具版本脱节——应以实时完整 Schema 为准，模板不可盲信
- 报错与传入值一致（值确实拼错、不在允许集）——直接改值即可，取全量 Schema 属过度动作
- 单字段无歧义工具——模板与 schema 无差异，本方法无增益
