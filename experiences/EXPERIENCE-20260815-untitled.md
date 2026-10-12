---
title: 并行多会话工作区的验证失效与契约碰撞处理模式
scenario: 并行多会话协作同一仓库时，验证结论失效、契约测试被顶破、新默认行为波及旧单测
root_cause: 多并行会话共享工作区无锁协调，各自改动在时间上交错；新功能默认开启改变了全局行为面（DNS 私网拦截），波及不相干测试；体量契约（946 行）未随功能增长同步拆分。
solution: 1) 验证前先 git diff --stat + mtime 确认验证对象稳定性；2) 契约测试失败 = 施工碰撞信号，新增块拆 mixin 恢复契约；3) 新默认行为全量跑旧单测，非聚焦测试用 monkeypatch 关闭新行为；4) 缺口验证测试修复后翻转为回归守卫保留。
evidence: 2026-08-15 会话实测：test_orphan_tool_calls_on_interrupt.py 双场景翻转；git diff tool_exec.py +88 行（HARNESS-01 _synthesize_cancelled）；web_fetch.py HARNESS-03 + VPN 198.18/15 私网判定导致 test_web_m48/test_web_fetch_paging 14 个失败；engine.py 955→898 行（archive.py mixin 拆分）；最终 1244 passed / 0 failed。文档：docs/local/ANALYSIS-20260815-agent-attribution-and-harness-kernel.md 第三轮更新。
tags: [并行会话, 契约测试, 验证翻转, SSRF, DNS劫持, mixin拆分, 协作模式]
source: {}
status: active
created_at: "2026-08-15T02:38:57.873323+08:00"
updated_at: "2026-08-15T02:38:57.873323+08:00"
---

场景：llm-first-loop 项目存在多个并行 Claude Code 会话同时改同一仓库（人类用户同时在跑多路任务）。本会话验证「中断孤儿 tool_calls」缺口时，两小时内工作区被并行会话改动 20+ 文件（feishu 功能 + HARNESS-01/03 修复系列），导致本会话结论三度翻转：初测发现缺口 → 重测发现缺口已被并行会话修复（测试断言失效）→ 修复又顶破既有契约（engine.py 行数、SSRF 拦截导致 14 个旧单测失效）。

教训与模式：
1. **验证类结论必须带时间戳和代码快照意识**：「现状验证」在并行开发环境下是瞬态事实，断言「缺口存在」前先看 git diff --stat 和文件 mtime，确认验证对象没有正在被别人改。
2. **契约测试是并行会话的碰撞传感器**：test_loop_mixin_split（engine.py < 946 行）这类体量契约在多方同时加代码时最先破，破了说明有人在同区域施工——修复方式是把新增块拆到 mixin（M53 模式延续），而不是放宽契约。
3. **新功能默认开启时，必须全量跑旧测试找碰撞面**：并行会话的 SSRF 拦截（HARNESS-03 默认开）+ 本机 VPN DNS 劫持（example.com 解析到 198.18/15，被 ipaddress.is_private 判定为私网）= 14 个既有单测集体失效。修复模式：非 SSRF 聚焦的测试统一 monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")。
4. **验证测试可以「翻转」为回归守卫**：缺口验证测试在修复落地后不应删除，改断言方向即成为防回归资产（test_orphan_tool_calls_on_interrupt.py 案例）。