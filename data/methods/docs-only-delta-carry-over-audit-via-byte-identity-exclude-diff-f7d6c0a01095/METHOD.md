---
method_id: docs-only-delta-carry-over-audit-via-byte-identity-exclude-diff-f7d6c0a01095
name: docs-only-delta-carry-over-audit-via-byte-identity-exclude-diff
description: 前轮审查已在某 commit 对运行源码/测试给出 PASS，交付 HEAD 随后声称仅 docs/receipt 增量时的补审法：用一条 git diff <源冻结commit>..<交付HEAD> -- . ':(exclude)docs' 的空输出，一石三鸟地证明运行代码跨三树字节相同（测试免重跑合法）、receipt 的字节锚定声明成立、前轮代码 PASS 可整体继承；再只对 docs 增量逐 hunk 审三害（自相矛盾/篡改历史/虚假PASS），并保持事件归属（旧exit=1 vs 新NOT_RUN）与角色区分（源修复commit vs 交付HEAD）不混淆，最后在精确 HEAD 上合并出冻结裁决。
aliases: 只改了回执的提交还要重审吗, 证明代码零改动免跑测试, 两轮审查结论合并成冻结裁决, 收据补丁防翻供核查, receipt修订后历史有没有被改
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d324e1a9-2f27-4e42-aaf3-680d2917311c:93:f4376152ae65e0a3c008
evidence_refs: learning:learn:c8c9092619c9
created_at: 2026-11-14T09:48:07.658853+08:00
updated_at: 2026-11-14T09:48:07.658853+08:00
---
## Trigger
上一轮独立审查已对 commit X 的全部运行源码/测试给出 PASS，现交付 HEAD（X 的后代）声称自 X 或更早源冻结点以来仅 docs/receipt 文件变更，任务要求合并两轮结论并裁决是否需重跑/重审。

## Discriminator
exclude-diff 空输出这一单一 git 事实：diff 源冻结commit..交付HEAD 排除 docs 目录输出为空。它把候选空间从『重审全部文件或重跑测试』缩成『只审 N 行 docs 增量』，且同时充当测试免跑、receipt 锚点声明、PASS 继承三项结论的共同许可证；非空则一切继承作废。注意区间起点应取源冻结 commit（代码最后变动处）而非仅上一审查点，才能覆盖 receipt 声称的锚定树。

## Short path
- 钉交付身份：rev-parse HEAD/tree/单父链 + status --porcelain 空（顺带消解前轮『脏工作树』finding）
- 读全量增量：diff --stat + name-status + 完整 patch，实测变更恰为声明的 docs 文件与行数
- 字节同一性证明：diff 源冻结commit..交付HEAD -- . ':(exclude)docs' 为空 ⇒ 测试免跑 + 代码PASS继承 + receipt锚点声明三合一成立
- 防改写核对：把链上每个历史 commit/tree 与前轮记录值逐一对照，全部相同 ⇒ 零历史改写
- 只审 docs 增量三害：新旧数字/候选是否分列（自相矛盾）、历史快照字段是否被原样保留（篡改）、NOT_RUN 是否仍为 NOT_RUN 且 exit=1 仍归属修复前候选（虚假PASS）
- 合并输出：代码结论按字节继承 + docs 增量裁决 + 脏树finding消解 ⇒ 在精确 commit/tree 上给最终冻结裁决与是否放行后续闸门

## Stop conditions
- exclude-diff 非空：任何非 docs 字节变化 ⇒ 继承失效，必须对新代码重新审查或重跑受影响测试
- 链上历史 commit/tree 与前轮记录不符 ⇒ 疑似改写，停止合并并单独上报
- receipt 把 NOT_RUN 或旧 exit=1 翻成 PASS，或把分环境数字混算 ⇒ 虚假PASS，判 REVISE 而非 PASS
- 交付 HEAD 工作树仍脏 ⇒ 前轮该 finding 未消解，不出最终 PASS
- receipt 内嵌的哈希与独立重算不一致 ⇒ 内嵌字段不可作真值

## Verification
- 对声明核验的对象独立重算（如逐文件 sha256+bytes），不采信 receipt 内嵌字段
- 确认所有 NOT_RUN 字段原文未动、旧 exit=1 仍指向修复前候选 commit
- 确认 receipt 对 commit 的引用只是锚点说明，身份真值以 git rev-parse 实测 HEAD/tree 为准
- 确认 docs 增量的每个 hunk 落点：只动顶层说明/新增字段，未触碰历史快照与验证矩阵

## Counterexamples
- 增量触及任何非 docs 路径（哪怕一行源码）⇒ 字节同一性不成立，前轮 PASS 不可继承
- receipt 修改的是 batches[] 等历史快照本体而非顶层追加注记 ⇒ 这恰是篡改，docs-only 低风险假设失效
- 前轮 PASS 的文件覆盖面小于字节相同集合 ⇒ 只能部分继承，缺口文件需单独审
- 审查区间外还有其他并行会话的提交未被 diff 区间覆盖 ⇒ 先补齐区间再裁决
