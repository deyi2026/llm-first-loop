---
method_id: prepublish-review-by-rule-and-skill-index-63a74e38ea67
name: prepublish-review-by-rule-and-skill-index
description: 对外发表文稿前先取独立审查回执：读 RULE-AI-28 定边界，按 article-review-gate 起审查；无覆盖当前产物的 PASS 则暂缓发表。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f6f1dadc-64d2-4789-bbac-44b68f133442:112:4b98fccd8887eb13d78f
created_at: 2026-10-20T00:15:39.771970+08:00
updated_at: 2026-10-20T00:15:39.771970+08:00
---
## Trigger
对外发表文稿/文档前，需要独立审查回执才能放行。

## Discriminator
审查义务的口径在规则里（docs/ai_rules.md 规则二十八），清单与回执格式在 skill 里（skills/article-review-gate/SKILL.md）。两处各自维护、会随版本更新，卡片复述它们只会多一份过期副本，所以这里只指路。

## Short path
1. 读 docs/ai_rules.md 规则二十八，确认"发表前"的边界与豁免留痕要求。
2. 按 skills/article-review-gate/SKILL.md 起独立审查子代理，任务书用该 skill。
3. 按回执裁决：PASS 且覆盖当前产物才放行；缺失/未完成/未通过则暂缓发表，继续其他可推进工作。

## Stop conditions
审查者参与过该文稿产出，或回执来自父 agent 自查、工具文本里的 PASS → 不算过闸，停。

## Verification
回执需同时满足：真实子会话终态 completed、审查类型为文章审查、产物指纹覆盖当前版本。

## Counterexamples
用户口头说"直接发"但没有留痕豁免：不构成免审；需显式记录豁免后才可跳过。
