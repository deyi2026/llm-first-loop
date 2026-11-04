---
method_id: slug-normalize-ledger-grep-key-before-broad-discovery-32ffa4ad42b0
name: slug-normalize-ledger-grep-key-before-broad-discovery
description: append-only 台账/索引以 slug 化标题为键（空格/标点转连字符）时，拿人类可读标题做文本 grep 会稳定 miss。miss 的第一假设应是键编码不匹配而非记录不存在：命名规则就在你已读过的回执里（search_records 命中行的 experience_ref=、台账 tail 的 id= 都展示连字符 slug 格式）。把检索键换成 slug 形式或最长无空格词根，在同一文件重试一次；命中即按行号定点读取。只有规范化后仍 miss 才扩大到 search_files/目录枚举。本集可省两次空 grep、三次 60s 超时与无关目录枚举。
aliases: grep 搜不到台账记录先看连字符 id 格式, 标题带空格 grep 不中就转 slug 重试, 记录明明存在却检索 miss：键被连字符化, 照回执里的 ref 样式改写检索词, usage 台账按连字符标题搜
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:924c084a-15a9-4599-8ec2-dbeb07e01797:139:80a58352d9805b2ddeb8
evidence_refs: learning:learn:a1c10c83025a
created_at: 2026-11-04T15:36:33.255349+08:00
updated_at: 2026-11-04T15:36:33.255349+08:00
---
## Trigger
在以 slug 化 id 为键的 append-only 台账/索引（usage ledger、记录索引文件）中，用已知存在记录的人类可读标题或带空格的短语做文本检索，回执为空

## Discriminator
发 grep 之前同上下文已读的行已展示键格式：search_records 命中行的 experience_ref=…-…-… 与台账 tail 的 id= 均为连字符 slug（空格/标点被剥除）；而拟检索键保留标题原文的空格/引号/括号——编码不匹配在动手前即可判知

## Short path
- 从已读卡片/上轮结论确认目标记录标题与用途（本集 card_53.md 已读出含空格标题）
- 从上下文中已读回执（search_records 命中行、台账 tail 的 id/experience_ref 字段）读出该 store 的 slug 规则
- 把 grep 键规范化为 slug 形式，或取最长不含空格/标点的词根，在同一台账文件重试一次
- 命中后按行号定点读取完整记录（sed -n 'Np'），形成对旧记录的裁决
- 执行原任务动作（如 record_use 更正），并以台账行数+1 且末行指向同一 ref 核对落账后停止

## Stop conditions
- 规范化键命中且已完整读取目标记录：转入原任务动作（更正/引用），停止发现
- 规范化重试一次仍为空：判定该记录当前确实不存在，停止换键重试，不进入宽枚举
- 已读回执显示该 store 键保留原文（无 slug 化证据）：直接用原文键检索，不套用本方法

## Verification
- 命中行的 id/experience_ref 与目标标题的 slug 化结果逐段一致（连字符分段对应原词）
- 动作落账后 tail 台账：新增行指向同一 ref，旧记录行未被改动（追加而非覆盖）

## Counterexamples
- store 键保留原文空格/标点（无 slug 化证据）：应直接用原文 grep，slug 化反而会 miss
- miss 的真因是记录确实尚未写入（如本班动作未落账）：规范化重试仍空即判不存在并停止，不得继续换措辞
- 检索走的是语义/记录检索工具（如 search_records，已做分词与规范化）：miss 不指向文本键编码问题，本方法不适用
