---
method_id: term-anchored-claim-direct-search-scope-and-age-graded-absence-3da8dd958f74
name: term-anchored-claim-direct-search-scope-and-age-graded-absence
description: 用户问『我们是否聊过/用过某确切术语X』（term-anchored 主张）时，一次 kind=all 的直译词记录检索即可裁决——同义/相关词变体检索对『出现过该词』的主张零判别力，不要换词考古。所有否定性结论只引用与其作用域匹配的证据：检索回执自带的 scope 参数（如 pattern-only、content=- 就不是内容零命中证据）声明了零命中能证明什么；记忆里的『零命中』是带时间戳的工作区快照，若同一回执中可见更新产物，则须用内容级 live 探针复核当前态。命中行自带 file:line 与逐字引用，够答即停。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:dac20fba-3f6c-4270-8425-f6e4861951ea:160:0636b92e7664ce5d60c6
evidence_refs: learning:learn:3e49c30d7b2a
created_at: 2026-10-20T12:17:43.936708+08:00
updated_at: 2026-10-20T12:17:43.936708+08:00
---
## Trigger
用户以确切术语为锚询问过去的讨论/记录是否存在（『我们聊过X吗』），且/或直译词检索的唯一命中本身是一条 absence 断言；或需要用某次零命中回执支撑『不存在/从未讨论』类结论

## Discriminator
直译词 kind=all 回执已穷尽含该词的全部记录，而用户主张以该词本身为锚——换关键词变体不增加判别力；每次零命中回执自印 scope（『pattern=worldshell, content=-』即仅测过文件名，不是内容证据）；唯一命中若是 absence 记忆，其时间戳（10-14）与同回执中可见的更新产物（10-20 报告 episode）相比即暴露快照已过期

## Short path
- 一次 search_records(kind=all, query=用户原词) 裁决『是否有被存储的讨论』；同一回执顺手提取：唯一命中是否为 absence 记录、是否存在更新产物及其路径
- 若 absence 记录断言工作区状态且早于回执中可见的更新产物 → 一次内容级工作区检索（pattern+content，勿用仅文件名 glob）复核当前态
- 只消费命中行自带的 file:line 与逐字引用（含悬置问题原文）；引用已含答案所需段落则不再补读
- 作答：每条否定结论标注支撑回执的 scope 与时间戳；结尾只把产物自己留下的悬置问题抛回用户；停止，不做关键词变体检索或结构再枚举

## Stop conditions
- 直译词 kind=all 检索已完成，且最终答案中每条否定断言都能映射到一条 scope 覆盖该断言的回执
- 早于新产物的 absence 记录已用内容级 live 探针复核过当前态
- 命中引用已逐字包含答案所需段落（悬置问题/关键结论），无需追加读取或再检索

## Verification
- 对答案中每个『没有/不存在/从未』，能指认支撑回执的工具、scope 参数、覆盖的记录 kind；对基于记忆的 absence，指认记录时间戳 vs 最新产物时间
- 确认除用户原词外未发起换词检索（除非主张是 concept-anchored）
- 确认抛给用户的收尾问题在产物原文中存在（如报告待答问题原句），而非新造

## Counterexamples
- 用户问题是 concept-anchored（『这个想法不管当时叫什么都算』）→ 同义词变体检索正是正确扩展，本方法会误伤
- 零命中回执已显示 content=true 且索引覆盖可信、absence 记录为当天且无更新写入 → 免 live 复核，直接作答
- 直译词检索即返回真实存储的对话 → 直接引用作答，无需工作区探针或 scope 分析
- 用户主张本身指向文件名（『我们建过 worldshell.py』）→ 文件名 scope 才是匹配探针，改成内容检索反而错配
