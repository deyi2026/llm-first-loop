---
title: exact-name 匹配失败先核码位：零宽字符陷阱与 playwright_exec 的正确定位
scenario: "browser_operate 按 exact name 点知乎某行「更多」失败；曾误判为\"语义层找不到控件\"并考虑改走 playwright_exec 裸脚本通道。"
root_cause: ""
solution: 失败后先 hydrate/snapshot 拿到目标 name 的原始字节并核对码位（U+200B/U+00A0/RLM 等不可见字符是常见根因），再把观察到的精确字符串原样作为 target.name 传给 browser_operate；playwright_exec 仅作显式逃生通道，脚本由模型逐行确定，不让程序猜目标。
evidence: ""
tags: [browser, grounding, exact-match, zero-width-char, diagnosis]
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-10-10T20:06:16.170285+08:00"
updated_at: "2026-10-10T20:06:16.170285+08:00"
---

背景：在知乎等站点用 browser_operate 点击某行「更多」按钮，exact name 匹配失败。视觉/复制文本是"更多"，AX 树里 name 实为 "\u200b更多"（U+200B 零宽空格前缀）。曾据失败现象推断"语义层找不到该控件"并倾向改用 playwright_exec，该推断与架构方向均错误（U+200B 事实来自用户对 AX 树的核对，本会话未独立复验）。
教训与做法：
1. exact-name grounding 失败时，先取目标 name 的原始字节并核对码位（重点排查 U+200B、U+00A0、RLM/LRM、全角空格），再下"层找不到"的结论；不要从失败现象直接推根因。
2. 正确修复是把观察到的精确字符串（含不可见字符）原样作为 target.name 传入，保持 exact-match 契约；不需要也不应为此引入 fuzzy 匹配。
3. playwright_exec 定位：显式逃生通道，仅当语义层确实无法建立 grounding（canvas、shadow DOM、虚拟列表等）时使用；脚本须由模型逐行确定目标与动作，不得让脚本自行"找按钮"。