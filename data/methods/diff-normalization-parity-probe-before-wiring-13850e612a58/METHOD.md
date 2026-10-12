---
method_id: diff-normalization-parity-probe-before-wiring-13850e612a58
name: diff-normalization-parity-probe-before-wiring
description: 重构把既有内联归一化（如 q = query.lower()）替换为共享 helper 时，编辑回执 diff 里被删除的归一化行就是最强判别事实：若新实现未等价恢复（本例 _query_terms 漏 .lower() 而 hay 侧仍 .lower()），含大写的查询（EVO-…/DC-1）会结构性落空；回归失败后又易与外部事件（merge 吞改动）混淆归因。方法：写入时逐行核对被删预处理是否有等价替代，用跨大小写最小探针验证 helper 语义后再接入多调用面；确定性单测失败先自查最近 diff 与文件 sha/快照一致性，最后才归因环境。附带：全仓搜私有下划线名只会命中 evals 归档副本，找测试应搜公共入口符号。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:76:69776549038d0746acae
evidence_refs: learning:learn:a7e286cba209
created_at: 2026-09-18T13:47:01.490244+00:00
updated_at: 2026-09-18T13:47:01.490244+00:00
---
## Trigger
用 helper/重构替换既有内联归一化或匹配语义（lower/strip/decode 等），或：编辑后确定性本地单测失败，且同时存在自身改动与环境事件多个候选归因。

## Discriminator
编辑回执 diff 本身：被删除的归一化行（q = query.lower()）与新增实现是否等价。本例 _query_terms 的 docstring 承诺“小写化”但函数体无 .lower()，而 hay 仍以 .lower() 构建——这一不对称在写入回执时即已可见，无需等回归测试暴露，也不依赖事后才知道的答案。

## Short path
- 改前先跑基线测试，记录通过数作为对照。
- 写入 helper 时逐行对照 diff：每处被删除的预处理/归一化必须在新路径有等价替代，不一致就地修复（如补回 .lower()）。
- 用一个跨大小写最小探针验证 helper 语义（如 _hay_matches('evo-1', _query_terms('EVO-1')) 应为 True），通过后才接入其余调用面。
- 统一接入后回归 + 一个含大写真实标识（如 EVO-…）的端到端查询各一次。
- 若回归失败：先核最近 diff 的归一化对称性，再核文件 sha/快照与预期一致（排除外部事件吞改动），最后才考虑环境归因。
- 定位测试覆盖面时在 tests 目录搜公共入口符号（如 RecordSearcher），跳过 evals/*/results/runtime-* 下的归档源码副本。

## Stop conditions
- 跨大小写探针通过且回归结果与基线逐项一致（含大写 id 查询能命中），即停止诊断，不再枚举其他归因假设。
- 失败被定位为单一可复现因素、修复并验证一次后即停，不重复确认。

## Verification
- 回归测试与改前基线完全一致（本例 44/44）。
- 真实数据端到端：按含大写的真实记录 id 查询能命中。
- git diff 中不存在“docstring/注释承诺归一化但实现缺失”的不对称。

## Counterexamples
- 旧代码本无任何归一化（查询侧与 hay 均原样比较）时无不对称可查，直接跑回归即可，探针无增益。
- 失败测试位于未改动模块且标记为环境敏感/非确定性（网络、顺序依赖）时，应先隔离环境因素，自查 diff 收益低。
- helper 为纯结构拆分、两侧共用同一归一化路径（无语义契约变化）时，无需归一化对等检查。
- 写入回执的“复读一致”只证明字节正确，不能替代归一化语义探针。
