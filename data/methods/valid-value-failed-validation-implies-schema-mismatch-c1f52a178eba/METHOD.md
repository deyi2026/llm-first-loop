---
method_id: valid-value-failed-validation-implies-schema-mismatch-c1f52a178eba
name: valid-value-failed-validation-implies-schema-mismatch
description: 类型化工具返回确定性参数校验错误，但本次已传入的值本就满足错误信息所述约束（如值就在枚举列表里）时，失败原因不在取值而在字段绑定/协议形状。此时应立即做一次权威 schema 内省，按 schema 重绑参数后单次重发；不要原样重试。本例同一参数错误连错两次后读 schema 才发现 restart 绑定 target 而非 restart_target 字段。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:895:13242afe2ab28c4d1ea2
evidence_refs: learning:learn:6a16e377eeea
created_at: 2026-09-24T00:54:50.541108+00:00
updated_at: 2026-09-24T00:54:50.541108+00:00
---
## Trigger
工具调用返回非瞬时的参数校验/枚举校验错误，且调用时实际传入的参数值与错误信息所声称的约束逐字相符（值合法但校验仍失败）。

## Discriminator
把实际传参（字段名+值）与错误信息声称的约束逐字 diff：若已传值满足约束（如 'web' 就在 '必须是 web/feishu/learning/all' 之列）而校验仍失败，即可判定为字段名/绑定不匹配而非取值错误；此时唯一能回答"服务端真正读取哪个字段"的权威来源是该工具的 schema，盲试重发不产生新信息。

## Short path
- 首次校验失败后先 diff：已传值 vs 错误声明的约束（未知量：错在值还是错在绑定）。
- 值满足约束 → 判定为字段绑定/协议形状不匹配 → 调用一次该工具的 schema 内省（未知量：服务端期望的字段名与参数形状）。
- 按 schema 重绑参数（如 restart 用 target 字段），单次重发修正调用。
- 以成功受理回执（action_id/generation 等凭据）验证绑定正确，随即回到原任务主线，不再触碰该分支。

## Stop conditions
- schema 已到手且修正调用被受理（拿到 success 回执/action_id），该分支立即关闭。
- diff 发现传入值确实违反约束（如枚举拼写错）→ 直接改值重发即可，无需 schema 内省。
- 环境无 schema 内省通道（不透明接口）→ 最多一次最小变体或转而询问，禁止反复盲试。

## Verification
- 修正调用返回 success 受据，且其中 action/target 与原始意图一致。
- trace 中同一形参错误至多出现一次，不存在同形重复失败调用。

## Counterexamples
- 错误所列约束被传入值真正违反（枚举拼写错误）→ 直接改值重试即可，读 schema 是多余开销。
- 瞬态失败（超时/5xx/锁竞争）→ 原样重试可能正是正确动作，本方法不适用。
- 无 schema 可内省的自然语言/不透明 API → 无法套用，应改为重述请求或向用户/文档询问。
