---
method_id: premise-recheck-by-named-id-before-executing-prior-round-plan-52f677bc6ad0
name: premise-recheck-by-named-id-before-executing-prior-round-plan
description: 用户用菜单单项/极简指令激活上一轮起草的行动计划时，该计划携带的是旧快照，前提视为未验证。本轮已有的权威状态回执（帮助收件箱计数、队列、lane 账本）若已枚举前提对象并显示其消失/终态，即是最便宜的真相源：用计划自带的具体标识符（请求 id / 目标会话 / lane）定点直读其终态记录（如 done/<id>.json）。前提被证伪→计划作废，向用户更正上一轮错误陈述，不执行任何机制侧动作（注入/唤醒/重下单）。前提成立→才转向执行机制调查。注意回执覆盖面：绑定字段未传的结论（如 main_head 为空时的 stale:false）按 fail-closed 不采信。
aliases: 用户选了旧选项先核对前提再动, 菜单单选命中过期计划, 唤醒别的会话前先重查收件箱, pending 可能早被对方自己清了, 单字母指令重验阻塞前提, 旧快照blocking是否还在
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:2005:71c24044d956e3bbe6b7
evidence_refs: learning:learn:830e062e8c24
created_at: 2026-11-08T12:36:00.943153+08:00
updated_at: 2026-11-08T12:36:00.943153+08:00
---
## Trigger
用户用菜单单项/极简指令激活上一轮起草的计划或基于旧快照的报告，且该计划依赖可变世界状态（pending 请求、队列、lane 状态、其他会话进度）才能成立

## Discriminator
本轮开始时已存在两件事：① 一条与计划前提矛盾的状态回执（如收件箱 pending=0 blocking=0，而旧计划称仍有一条 blocking）；② 计划文本自带前提对象的具体标识符（请求 id / 目标 session / lane）。二者合起来把『怎么执行计划/仓库全貌』缩成『这几个具名对象去哪了』，一次定点读取即可裁决，无需宽枚举或先查注入机制

## Short path
- 把菜单项映射回上一轮计划，抽出其前提子句与具体标识符（请求 id / 目标会话 / lane / 路径）
- 先对本轮已到手的状态回执：前提对象若已被枚举为空/终态，唯一未知量定为『这几个 id 的终态记录』
- 按精确 id 定点读终态记录（如 done/<id>.json、lane 账本行）：确认谁、何时、以何理由处理
- 前提证伪→计划作废：不执行注入/唤醒/重下单，向用户显式更正上一轮基于旧快照的错误陈述；前提部分存活→只对存活子目标核实并执行
- 仅当本轮回执覆盖不了前提对象时，才做一次 scoped 探测（列该 store 目录），仍不升级为全仓枚举或执行机制调查

## Stop conditions
- 两条目标记录均确认终态且由目标会话本人 resolve（resolved_at + response 完整）→ 前提消失，停止核实，不得注入/唤醒任何人
- 本轮状态回执与计划前提一致（如 pending 仍>0）→ 停止重复核验循环，转向执行机制未知量
- 回执绑定字段缺失（未传 main_head 等）导致结论分母不明 → fail-closed 不采信，改用直读 store 验证一次

## Verification
- 终态记录的 resolved_at/by_session 与目标会话自身一致，response 内容解释了处置方式与后续承诺（如 ETA）
- 收件箱计数与 store 目录实况（pending 空 / done 含目标文件）两个独立来源互相印证
- 向用户更正上一轮陈述前，手头至少有一条本轮回执或一次定点直读作为证据，不凭推断翻案

## Counterexamples
- 菜单项动作不依赖世界状态前提（如『跑全量测试』）→ 无前提可核，直接执行
- 本轮回执显示前提对象仍存在（pending>0、lane 仍 active）→ 前提存活，应直接进入执行机制调查而非反复重验
- 前提对象没有可按 id 枚举的权威 store（无收件箱/无账本）→ 新回执无法证伪前提，本方法退化为对目标本身的探测，不适用
- 时间紧迫且核实延迟高于动作成本（如紧急止损）→ 先行动后核实
