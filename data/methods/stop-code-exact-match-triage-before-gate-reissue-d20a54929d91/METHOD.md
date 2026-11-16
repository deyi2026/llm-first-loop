---
method_id: stop-code-exact-match-triage-before-gate-reissue-d20a54929d91
name: stop-code-exact-match-triage-before-gate-reissue
description: 任务书以命名错误码枚举受管动作的停止条件（如 split_plan/超限→报告并停，且停止时禁止强行放宽），而门实际回执是另一个命名码、reason 自带算术依据（估算≤预算）与逐字重发指令（移除 paths、整量 start）时：先按码精确比对停止谓词表再行动。未命中停止码且回执明确给出重发形态→在同一父 run 内机械重发一次，即使该表面动作与停止情形下被禁动作同形；命中或歧义→停/上报。与『rejection 即合同差分重发』卡互补：那张管补字段方向，这张管停止表分流与删参/放宽 scope 方向。
aliases: 审查start被拒要不要停, 被拒先对停止条件再重发, Host说不得分批要整量怎么办, 拒绝码和停止条件对不上, 删掉paths整量重审, 按回执指令改参数重发一次
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a43dc767-17c2-429a-82f3-1dd9d4aa5558:253:3f3c49af39821d003429
evidence_refs: learning:learn:3e251442af64
created_at: 2026-11-15T22:23:37.178146+08:00
updated_at: 2026-11-15T22:23:37.178146+08:00
---
## Trigger
受管准入/审查门对按任务书原文发起的首次调用返回 accepted:false，且任务书同时枚举了『哪些命名码必须停止、停止时禁止哪些补救动作』（例如拒绝分批时禁止强行整量）

## Discriminator
回执命名码与 reason 内算术的极性：『全量估算 870s ≤ 预算 3600s，整量可行，不得分批（移除 paths 整量 start）』与停止谓词『split_plan/超限』方向相反，且重发形态由回执逐字给出——首次调用时无法预知该算术，故拒绝回执本身就是当时唯一可判定的分流依据

## Short path
- 按任务书原文发起首次受管调用：分批/整量由门按预算动态裁定，不可预判，不 preemptively 改参数
- 收到 accepted:false 后先做一次纯分类：把回执命名码与 reason 中的算术/指令，逐字比对任务书枚举的停止谓词
- 命中停止码→报告并停，不尝试任何补救；未命中且 reason 明确给出重发形态（移除 paths、scope 转 tree）→在同一父 run 内按该形态机械重发一次
- 重发 accepted 后核对回执形态与 reason 预言一致（scope、估算口径、被审身份），再继续任务书规定的后续协议（同 run 轮询、凭资格字段消费、远端核验）

## Stop conditions
- 回执码命中任务书枚举的停止谓词（split_plan/超限类）→ 立即报告并停止
- reason 未给出明确重发形态，或与停止谓词无法区分（歧义）→ 上报，不猜方向
- 按 reason 重发后再次被拒 → 不做二次临场发挥，视为新事实上报

## Verification
- 重发 accepted 回执的 scope/paths_ignored/估算口径应与首次拒绝 reason 预言的形态一致
- 下游受管动作只凭机器资格字段（如 qualification=PASS）消费资格，不凭回执文本线索

## Counterexamples
- 回执码就是枚举的 split_plan/超限：即使『整量更严格』看似合理，也绝不能自行放宽——那正是任务书明令禁止的强行路径
- reason 只有定性批评（材料不合格/范围越权）而无重发指令：属 REVISE/上报流程，不适用机械重发
- 任务书是白名单式『任何拒绝都停』：分类结果即停，不存在重发分支
