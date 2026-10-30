---
method_id: verify-cited-spans-directly-skip-dialogue-reconstruction-19517dd6e6ce
name: verify-cited-spans-directly-skip-dialogue-reconstruction
description: 用户修正/建议消息自带精确锚点（文件:行号＋行为语义）并说明是在回答早前问题时，该消息即自足：先由引用语义定位 canonical live 文件，直读被引 span 逐条裁决；断言涉及实现细节再 grep 符号读实现体；然后读待修订文档现行段落落编辑。不要全库按文件名枚举（会命中 .venv/.releases 冻结副本，无法裁决『现行门槛』），也不要为找回原始问题原文反复搜 evidence/records/事件流——被否定的前提已全部在消息中重述，原文只是锦上添花，一次尝试不中即弃，不作为执行前置。
aliases: 用户给了行号还全库搜文件名, 先读用户指的那几行再动手, 原问题找不回来就卡住了, 别翻聊天记录核代码, venv 里一堆同名文件怎么选
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e827e946-e151-4ded-9bdf-58c042570992:0:0f46d8767509bfd726bb
evidence_refs: learning:learn:ba2871d8145e
created_at: 2026-10-30T13:23:00.768407+08:00
updated_at: 2026-10-30T13:23:00.768407+08:00
---
## Trigger
用户消息逐条给出权威工件的精确引用（文件:行号＋行为描述），且自称是对早前某问题的回答；当前任务是对这些断言做核验并落地修订

## Discriminator
消息是否已重述全部关键前提（引文＋行号＋语义）——是则『找回原问题原文』不是执行前置；且引用的内容语义（涉及哪个子系统/哪类对象）已足以唯一确定 canonical live 路径，无需枚举同名文件

## Short path
- 由引用语义＋仓库布局推 canonical live 路径，一次路径存在性查询确认，不做全库文件名枚举
- 直读各被引行号 span 逐条裁决断言；行号与内容明显对不上时先 grep 符号重定位再读
- 断言涉及实现细节（如『不检查证据多样性』）时，grep 该符号并读其实现体确认
- 读待修订文档的现行段落，对照差异落编辑，用 grep 复核新措辞已写入
- 对『原始问题原文』的恢复至多一次尝试；事件流只存截断版时直接以消息自身引文继续执行

## Stop conditions
- 各条引文 span 与用户断言的一致/不一致均已实测确认并附实测行号
- 修订已写入文档且 grep 可命中新措辞
- 不再为还原早前对话原文而发起任何 evidence/records/event 搜索

## Verification
- 每条裁决附实测行号与函数名，不照抄用户给出的行号
- 若引用行号与实测内容漂移，先确认 live 文件未被并发修改（符号重定位）再下结论
- 修订后文档段落与用户各条建议逐条对应、可追溯

## Counterexamples
- 用户只给结论不给锚点（『那个门禁太严了，改一下』）——需 scoped 检索定位定义面，本卡不适用
- 任务目标本身就是还原对话内容（写纪要、审计谁说过什么）——恢复原文是任务本体而非前置，不可跳过
- 引用指向 vendored/快照副本且 live 行为可能与之不同——须先确认 live 权威路径，不能直读被引副本
