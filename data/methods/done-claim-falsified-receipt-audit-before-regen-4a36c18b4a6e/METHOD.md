---
method_id: done-claim-falsified-receipt-audit-before-regen-4a36c18b4a6e
name: done-claim-falsified-receipt-audit-before-regen
description: 上一会话/上一轮断言某具体产物已生成且『预演/校验通过』，而当前确定性检查（No such file or directory）证伪时，第一未知量不是『文件在哪』而是『该断言当时有没有回执支撑』。一次有界检索（产物在目标根 + deliverables 目录 + 按文件名查 evidence 回执）即可把『路径错』与『从未存在』分开：命中→修路径；双缺失→断言属『把打算当已做』，须显式订正记录、从权威现源重生成产物并真实跑一次校验拿回执，而不是继续宽搜环境或悄悄补文件了事。
aliases: 上轮说做完了实际文件不存在, 交接补丁找不到是不是根本没做过, 先查回执再重生成补丁, 把打算当成已经交付了, 已预演通过却 no such file
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:c2df336a-eb98-4baa-9220-9e80d36e4ee2:431:4e4f00416ef12dac3315
evidence_refs: learning:learn:efc7cec4d724
created_at: 2026-10-31T15:25:23.739184+08:00
updated_at: 2026-10-31T15:25:23.739184+08:00
---
## Trigger
上轮/交接断言某具体产物（补丁、报告、文件）已生成且已通过校验，但当前对同名产物的确定性存在检查失败（file not found / 404 / store 无记录）

## Discriminator
错误类型是产物级 not-found（确定性），而非格式/上下文冲突错误——这说明『已验证』断言隐含一张本应存在的校验回执；按产物文件名在有界范围（用户工作区、release worktree、deliverables 目录、evidence 回执库）一次检索即可裁决『路径/环境错』vs『从未做过』

## Short path
- 从错误文本定性：产物级 not-found 而非 apply 冲突 → 候选缩为两假设：路径错 vs 断言无支撑
- 一次有界存在性检索：目标工作区、release worktree、deliverables 目录，并按文件名在 evidence 库查『预演/校验』回执
- 命中产物 → 修路径交付（cp 到交接声称路径，重跑 --check 真实通过后再给命令）
- 产物与回执双缺失 → 判定断言=把打算当已做：显式向用户订正上轮说法，从权威现源（待改文档本身）重生成产物
- 真实执行一次校验并留回执，交付带绝对路径的可复制命令，停止

## Stop conditions
- 产物在交接声称路径真实存在且校验命令本轮真实执行成功（有回执 ref 入账）
- 已显式订正无支撑断言并交付经真实校验的替代产物
- 有界检索穷尽已知根仍无产物且无回执 → 停止环境宽搜，进入重生成分支

## Verification
- 最终产物路径可 stat/ls 证实存在，校验命令本轮真实执行成功且回执已入账
- 对用户明示『上轮断言无产物/回执支撑』这一订正，不留含糊
- 与 handoff 戳过期类问题区分：戳过期=曾经为真，本卡=从未存在，裁决依据是回执与产物双缺失而非时间先后

## Counterexamples
- 文件存在但 git apply 报格式/上下文冲突 → 是目标漂移问题，按当前 HEAD 重做 diff，不适用本卡
- 用户只是路径打错、产物在别处且确有回执 → 纯路径修复，不需订正记录或重生成
- 断言对象是无持久产物的瞬态动作（如『我重启了服务』）→ 应走动作后独立状态断言，不是文件存在性审计
- 环境没有 evidence/回执机制 → 只能靠存在性检索，『无支撑』结论须降级为『未找到』
