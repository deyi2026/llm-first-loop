---
method_id: drain-then-snapshot-supersede-then-freeze-on-peer-gate-block-341d0e153246
name: drain-then-snapshot-supersede-then-freeze-on-peer-gate-block
description: 共享仓里对方的受闸 push 被你的未跟踪知识产物阻断、并请求排他冻结窗口时，正确顺序是排干→定坐标→回执→冻结→复核：闸的语义是未跟踪知识资产为零，只冻结不解锁，必须先单笔 flush 把全部待入库资产折入一笔提交；该提交会移动 main tip，此前发出的『最终 SHA』按构造已过期，回执坐标必须取自入库提交之后并显式声明取代旧值；冻结窗口内零提交零落盘（含知识管线自动产卡），结束后先核 HEAD==回执坐标再恢复写入；退出码与输出内容矛盾时以回执内嵌锚点裁决而非重试。
aliases: 别人推送被我的未跟踪卡挡住, 先入库提交再报main坐标的顺序, 已发的最终SHA过期怎么更正, 配合对方独占推送别再提交, 闸被未跟踪方法卡挡住先排干
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:1a7bb31d-f3da-497f-9322-336483f4435a:979:0b0f0706f0a423fd94a9
evidence_refs: learning:learn:694bb9dd1260
created_at: 2026-11-14T15:22:13.460300+08:00
updated_at: 2026-11-14T15:22:13.460300+08:00
---
## Trigger
共享仓库中另一会话的受闸操作（如 push 前的 knowledge_flush/清洁度闸）被你的未跟踪知识产物阻断，对方请求排他写冻结窗口，并索要「已处理 + main 精确坐标」回执。

## Discriminator
对方消息与你的 git status 回执在动手前已共同表明三点：闸语义是未跟踪知识资产为零，解锁必须先落一次入库提交；该提交必移动 main tip，因此此前已发出的任何『最终 SHA』按构造过期，回执坐标必须在入库提交之后取样；flush 回执内嵌的完整 HEAD 与未跟踪计数即确认成功与否的权威锚点。

## Short path
- 枚举全部未跟踪知识产物（porcelain -u），不止对方点名那张：目标是单次排干，消除二次阻断
- 逐张最小核验后单次 flush 折入一笔提交；退出码与内容矛盾时以回执内嵌 HEAD_FULL/未跟踪计数锚点裁决，不重试（窗口内重试=多余提交）
- 从入库后的权威回执逐字转写新 main 全 SHA，回执对方：已入库 + SHA + 冻结声明，并显式声明取代此前发出的过期坐标
- 冻结窗口内绝对零提交零落盘（含知识蒸馏管线自动产卡），用定时等待度过而非轮询
- 窗口结束先核 HEAD==回执坐标且工作树净，再恢复任何写入

## Stop conditions
- 对方确认受闸操作已落地（远端 tip 与回执坐标相符）
- 窗口到期且复核 HEAD 与回执坐标逐字相等、未跟踪知识资产仍为零

## Verification
- 窗口后 rev-parse HEAD 与回执坐标逐字相等
- 未跟踪知识目录数为零、无新落盘卡出现
- 对方回执/远端推进与自己声明一致，未再收到第二次阻断报告

## Counterexamples
- 对方索要的是某笔固定提交（如入库提交本身）的 SHA 而非 main tip：坐标不可变，无需等写静默，随时可发
- 单写者仓库或无共享闸门：不存在排他窗口协调，正常提交流即可
- 你的未跟踪产物不属于闸门检查的资产类：只排干该类，不把无关在途工作仓促折入提交
- 对方只是顺口要状态、未宣布排他窗口：报当前 HEAD 即可，不启动冻结
