---
method_id: zero-hit-rescan-validate-pattern-on-known-positive-70c8c6ab7324
name: zero-hit-rescan-validate-pattern-on-known-positive
description: 对同一棵树/ref 的二次 grep 类扫描返回 exit 0 且零命中，而首轮回执在同树上已有该模式类的具体命中行时，不要采信更晚的"干净"结果：两轮之间唯一自变量是 pattern/调用形态。先用首轮的一条命中行做单点验证（同一 grep 引擎），样本不命中即证明 pattern 从未匹配（如 BSD git grep 不支持 \b 锚点），修好 pattern 再做全树普查；负结果才可作为"不存在"证据。同树已知命中行是当轮免费的反证测试，可在一个回执内裁决"树真干净 vs pattern 失效"。
aliases: grep 搜不到但之前明明搜到过, git grep 空结果可信吗, macOS grep \b 假阴性, 零命中先怀疑正则引擎, 空扫描拿已知命中行验证
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:3665:836060b6f9fa5e9227fd
evidence_refs: learning:learn:f0247d3efd1a
created_at: 2026-10-30T02:45:36.914764+08:00
updated_at: 2026-10-30T02:45:36.914764+08:00
---
## Trigger
同一 ref/树的二次扫描（隐私普查、泄漏面确认等 grep 类）返回成功退出码且零命中，但早前回执在同树上已列出该模式类的具体命中行；或两轮扫描之间只改动了 pattern/引擎方言（新增 \b、lookaround、-P 等）。

## Discriminator
首轮回执里已存在同树 known-positive 命中行；两轮间唯一变化的是 pattern/工具形态而非树内容（ref 未变）→ 结果翻转首先指向 pattern 在当前引擎里从未匹配，而非内容消失。

## Short path
- 首轮扫描后，把一条具体命中行固定为 known-positive 样本（一行即可）
- 换 pattern 或引擎方言（\b、lookaround、-P 等）前，先在该样本行上用同一 grep 引擎做单点验证
- 样本不命中 → 判定 pattern 失效，改写为该引擎支持的等价形式（去锚点/换 -P/固定串）后重验
- 样本命中后才做全树普查；此时零命中才可作为"不存在"证据
- 扩展：对同一扫描管线的其他静默负结果层（如 git quotePath 对非 ASCII 路径 C-quote 后被跳过）做同类 known-positive 抽查

## Stop conditions
- 新 pattern 在 known-positive 样本上命中，且全树普查结果与样本逻辑一致
- 已知正例确实来自不同 ref/已被他人清洗的旧内容：对齐 ref 并解释差异后，负结果可采信

## Verification
- 对每类"零命中"结论保留一条当轮反证：pattern 能重新命中已见过的命中行
- 引擎方言支持性（BSD/GNU、-E/-F/-P）用一行回执确认，不凭记忆断言

## Counterexamples
- 首轮命中来自不同 ref 或旧树，内容真被清洗过：先对齐 ref 再比较 pattern，零命中可能是真
- pattern 为纯固定串（-F）且不含方言语法：无需前置单点验证，可直接信负结果
- 目标存在性本来就未知、手头没有 known-positive 样本：本方法无从触发，应循 partial-coverage 类负存在判断
