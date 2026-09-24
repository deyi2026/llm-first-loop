---
method_id: falsify-behavior-premise-before-inherited-change-6c6091650c9c
name: falsify-behavior-premise-before-inherited-change
description: 当用户或上轮结论以'机制X只计算/声明而不产生效果'为前提提议改动（常带'差一根线'式表述）时，先检索X的效果证据（reason_code、BLOCKED回执、状态枚举、判定函数调用点）证伪前提，再决定是否进入设计。本episode中一次内容检索命中'executed=false; reason_code=convergence_boundary'，即推翻'算而未拦'前提：闸门已是双层阻断，提议的改动分支整体作废，真缺口转移到别处。该方法在动工前把设计空间缩为零。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:487:6141cabdc419ae01b13a
evidence_refs: learning:learn:13e3441e2788
created_at: 2026-09-23T23:49:54.103636+00:00
updated_at: 2026-09-23T23:49:54.103636+00:00
---
## Trigger
用户或先前轮次的自己提出以'当前代码/artifact 缺少某种效果'（如'算出来了没接闸门'）为前提的改动建议，且该机制是本地可检索的代码，断言可机械检验。

## Discriminator
该机制的效果面是否已有痕迹：检索 reason_code、状态串、BLOCKED/异常回执、判定函数调用点。任一命中（本例 executed=false; reason_code=convergence_boundary）都把候选空间从'如何设计改动'直接缩为'改动是否还有必要'——此事实在读取任何实现文件之前就已可见。

## Short path
- 把提议还原为前提断言：'机制X目前只计算，不改变任何执行结果'，明确这是待证伪的未知量
- 在本地代码检索X的效果证据（reason_code/回执/状态/调用点），先于任何外部资料发现或方案设计
- 若命中强制效果，精读判定点与执行点两处实现，确认强度等级（提示级 vs 面收窄+WAL栅栏级）
- 前提被证伪则宣告改动作废、显式报告新事实错误，并重排剩余分支——真缺口往往随之转移
- 仅对幸存分支行动，所需材料从已验证的权威来源直取，读至无具名缺口即停

## Stop conditions
- 前提已被本地效果证据证实或证伪：证实则进入设计，证伪则该分支作废并明告用户
- 断言对象不可本地检验（外部服务/他人仓库）时停止本地枚举，转向权威外部来源
- 已确认改动必要且其形态由证据定级后，停止核验进入实现或提请治理流程

## Verification
- 核对该效果字符串/行号确属当前版本代码，排除相似命名或二进制误报（本episode先例：.pyc 撞字节误报）
- 追溯'缺失'断言的原始出处（哪一轮、依据哪段文本），与刚读到的实现对照，矛盾处显式报告而非静默修正
- 确认前提原文的真实语义：如'不注入不持久化'是prompt-neutral承诺，并不等于'不阻断'，不得据半句文本下结论

## Counterexamples
- 前提是新增尚不存在的能力（如'加重试'），并无'现有行为是惰性'的断言——无对象可证伪，直接进入设计
- 断言是语义/架构判断（如'是否长成第二套解释器'），效果面grep命中无法裁决，需通读上下文与设计文档
- 断言针对外部系统的行为（hosted API限流、他人仓库内部状态），本地检索只能得到证据缺失，须直取权威外部来源
