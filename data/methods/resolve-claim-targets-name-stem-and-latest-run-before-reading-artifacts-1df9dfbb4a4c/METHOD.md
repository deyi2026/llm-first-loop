---
method_id: resolve-claim-targets-name-stem-and-latest-run-before-reading-artifacts-1df9dfbb4a4c
name: resolve-claim-targets-name-stem-and-latest-run-before-reading-artifacts
description: 复核一份引用某项目量化指标的外部分析时，先做『引用目标解析』再读内容：用检索回执里已出现的项目名称词干一步定位权威仓库（避免 ls 全 home、按通用名猜仓库、进无关 git log）；多副本先钉权威；核数字时用指标键名变体 grep 并按日期取最新生产 baseline，防止把旧沙箱结果当现值、也防止把真数字误判为错误引用；数字核完再读采用侧记录。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:cf1db8d6-5f5a-449e-9226-c1bdc6b0fa97:0:cca5926794a78cd42789
evidence_refs: learning:learn:1b07610106f5
created_at: 2026-10-22T23:12:32.526824+08:00
updated_at: 2026-10-22T23:12:32.526824+08:00
---
## Trigger
审查/复核一份以别名或缩写称呼某项目（如 LFL）、并引用其具体量化指标（如 hit@5=0.90、『生产路径』、『30 条冻结题』）的分析或报告，需要到本地文件系统核实时。

## Discriminator
发起任何目录枚举之前，检索/记录回执里已经出现该项目的名称词干（如 experience 卡 source 里的 session 名 llm-first-loop-mirror），足以一步名称模式定位仓库；且仓库 evals 目录存在多个不同日期的同类结果文件，指标散文写法（hit@5）与存储键名（h5/hit_at_5）常不一致，而被引数字自带『生产/最近』限定词。

## Short path
- 从已浮出的名称词干直接做名称模式定位（如 ls -d ~/*/*<词干>*），一步拿到 canonical/mirror/归档候选；不 ls 整个 home，不按直觉猜通用目录名（如 agent）后读其 git log。
- 多副本时先钉权威副本（含 data/evals 且时间较新，或有 README/AGENTS 声明），其余仅作对照。
- 核数字：用指标的多种写法（hit@5/hit_at_5/h5/具体数值/样本集名）grep 仓库，按文件名日期取最新 baseline/协议文件；旧沙箱 A/B 结果只作历史对照，不能用来证伪被引的生产数字，反之亦然。
- 被引数字证实或证伪后，再读同仓库的采用侧记录（usage 台账、池体检/漏斗报告），补齐『生成—使用』链的另一半证据，然后成文。

## Stop conditions
- 权威副本中最新运行文件已证实或证伪被引数字，且 ran_at/commit/goldset 规模对得上
- 项目到仓库的映射已唯一钉死，无 mirror/canonical 歧义
- 采用侧关键统计（使用覆盖、benefit 完整率）已从权威记录读出

## Verification
- 所读结果文件的 ran_at 时间、commit、goldset 规模与被引数字的语境一致
- 读的确实是声明『生产路径』的那条评测线，而非另一套沙箱/旧分支结果
- canonical 与 mirror 未错位：生产数据所在副本就是被读取的副本

## Counterexamples
- 当前工作目录就是该项目仓库：无需定位步骤，直接进入指标核验。
- 被引数字只存在于外部网页/论文，本地无产物：名称词干定位与最新运行判定都无意义，应走外部来源核验。
- 结果目录只有一个无日期歧义的结果文件：无需按日期选最新运行。
- 项目代号与目录命名完全脱钩（词干不共享）：词干定位必然失败，需查配置或问用户。
