---
title: "\"不以是否拦截为判据\"只适用于有指纹绑定的规则，不等于\"任何放行都算陷阱生效\""
scenario: "判定 admission-gated 卡实例时，第 2 轮把一条 article_publish 记录（准入后把命令去注释+追加管道，被放行执行）从 related_only 改判为 instance，理由是卡的反事实段覆盖\"静默放行\"路径。"
root_cause: "把\"不能以执行层是否拦截为判据\"这条正确原则外推到了它不覆盖的场景。卡 Trigger 的括号明确写\"target 字段含 command:<hash>\"；该条 cue 里自己就记了\"无 command:<hash> 绑定\"，却仍按反事实段改判，属自相矛盾。"
solution: "判定前先按 kind 统计 target 是否真含 command:<hash>：有指纹才谈\"改写导致指纹漂移\"；无指纹时命令怎么改写都不会造成绑定失效，应判 related_only。据此把该条回退。"
evidence: "本轮实测 68 条中：full_test 140/140 次准入含 command:<hash>、git_push 14/14 含、article_publish 0/23 含（target 均为 article_publish:确认发布/发表）。回退该条后池为 24 instance / 78 候选，精确率 30.8%。回退留痕写在该行 notes。"
tags: [规则判定, 反事实, 指纹绑定, 自我纠正, admission-gated]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-21T10:15:01.500392+08:00"
updated_at: "2026-10-21T10:15:01.500392+08:00"
---

可复用的判别顺序：
1. 先查 Trigger 要求绑定的对象是什么（命令指纹？产物指纹？还是仅动作类型）。
2. 按 kind 分组统计实际回执的 target 是否满足该要求——同一张卡的不同 kind 可能完全不同（本例 full_test/git_push 全绑命令，article_publish 全不绑）。
3. 只有满足绑定前提，才适用"被放行也算陷阱生效"的反事实推理。
4. 绑定前提不满足时，改写命令不构成卡定义的陷阱；用 related_only 并在 notes 写明"Trigger 不满足"，不要用 reject（题意仍相关）。

关联：方法卡 adjudicate-rule-instance-by-counterfactual-not-enforcement-firing-36ae88c1469d 的 Limits 已写明"规则文本明确把适用范围限定为指纹绑定型回执…无指纹确属卡范围之外"。本条是它的操作化补充：先核绑定，再谈拦截与否。