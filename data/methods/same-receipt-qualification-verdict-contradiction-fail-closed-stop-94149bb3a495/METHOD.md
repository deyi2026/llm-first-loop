---
method_id: same-receipt-qualification-verdict-contradiction-fail-closed-stop-94149bb3a495
name: same-receipt-qualification-verdict-contradiction-fail-closed-stop
description: 准入/放行回执在同一份回执内既给出机器判定（qualification=REVISE、reason=『verdict 缺失或非 PASS』类自描述错误），又逐字嵌入被审报告尾部结论行（如 VERDICT: PASS、P0=0 P1=0、绑定 SHA）时，矛盾本身就是卡点：缺陷大概率在门控侧的 verdict→qualification 解析，而非候选质量。不采信有利逐字读数自行执行被门控动作（全量测试/提交/发布），也不重开审查轮次；逐字摘录两段证据、冻结候选（SHA 不变）、给出两条最小解法（门控侧修解析、或人工核报告放行）后停在边界等决断。
aliases: 准入说 REVISE 但报告写 PASS, qualification 和 VERDICT 对不上, 回执内部打架先停还是先跑全量, verdict 明明 PASS 为什么不签资格, 门控解析 bug 卡住全量测试怎么办
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:289:55ada6aeda86467a52a0
evidence_refs: learning:learn:5717cd2e8d39
created_at: 2026-11-07T17:17:18.602538+08:00
updated_at: 2026-11-07T17:17:18.602538+08:00
---
## Trigger
放行/准入类门控返回的同一份回执内，机器判定字段（qualification=REVISE 或 accepted=false）与同回执逐字嵌入的审查报告结论行（VERDICT+计数+SHA）方向相反，且下一步重动作（全量测试、提交、发布）以该资格签发为前置。

## Discriminator
reason 字符串断言的缺陷能否被同一回执内逐字存在的 VERDICT 行直接证伪：判定行确实存在、结论明确、计数与 review_counts 一致 → 指向门控解析/提取 bug，不改候选；若 VERDICT 行确实缺失或被截断 → reason 属实，走正常补审路径。两段证据必须同源同回执，不得跨回执拼接。

## Short path
- 逐字摘出冲突双方：机器字段（qualification+reason 原文）与报告尾部判定行（含 SHA/计数），确认同属一次工具回执
- 判定 reason 的断言是否被同回执逐字内容证伪；证伪成立 → 缺陷定位为门控侧解析，候选无需任何改动
- 冻结候选：不再改动（回执中的绑定 SHA 即冻结基线），不执行被门控动作（不跑全量门/不提交/不发布）
- 回报矛盾本体+报告路径/SHA+两条最小解法（门控侧修 verdict→qualification 解析，或人工核报告原文后放行），停在边界等决断
- 资格正式签发后按原版门控命令执行，不因等待自行放宽或替换步骤

## Stop conditions
- 准入资格正式签发（门控侧修复或人工放行）前，被门控动作保持未启动
- 回报中已含双方逐字证据、报告路径/SHA 与最小解法后即停，不反复重试同一门控调用、不主动重开审查轮

## Verification
- 两段证据出自同一次工具回执而非跨回执拼接，报告 SHA 与当前候选一致
- 等待期间候选零改动：工作树 diff/SHA 与冻结时点一致
- 若走人工放行，人工核对的是报告原文路径，而非本会话的转述

## Counterexamples
- qualification=REVISE 且报告确列 P0/P1 发现项——不存在同回执逐字矛盾，禁止借『找矛盾』推翻不利判定（防动机性推理）
- 报告被截断、VERDICT 行确实读不到——reason 属实，应按 verdict_incomplete 补审/重发，不是解析 bug
- 冲突两段来自不同回执或不同 SHA 的报告——不构成本回执内部矛盾，各自按各自回执处理
- 门控字段与报告结论一致地 REVISE——正常返工路径，本方法不适用
