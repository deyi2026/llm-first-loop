---
method_id: prefix-anchored-parse-when-real-ids-embed-delimiter-6d4ced518933
name: prefix-anchored-parse-when-real-ids-embed-delimiter
description: 统一新旧两代记录格式的解析/校验时，规格串（如 <prefix>:<token>:<digest>）是理想化形状，真实 token 可能内嵌同一分隔符（如历史 attempt_id = pattempt:<hex> 自带冒号），真实段数随之漂移；解析若按固定段数 split，合成单测全绿后，真实 root 端到端才以 bad_receipt_ref 打回返工。第一份真实数据探针的输出当时已显示 token 的真实取值，应同步消费这一形状事实：解析锚定已知前缀+定长尾段，中间整体为 token；单测种子复刻真实复合形状，并保留段数/前缀异常仍 fail-closed 的负测。
aliases: 旧格式解析只认三段导致 bad receipt ref, token 内含冒号 split 多一段, 统一新旧格式解析先烟测真实历史记录, 复合 id 含分隔符用前缀和定长尾段锚定, 合成单测全绿但历史 root 校验失败
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:1560:baad39760fdb932aae55
evidence_refs: learning:learn:6b67a8a62862
created_at: 2026-11-14T00:34:06.009574+08:00
updated_at: 2026-11-14T00:34:06.009574+08:00
---
## Trigger
需要统一或改写解析/校验逻辑以同时覆盖新旧两代持久化记录格式，且格式以分隔符拼接串描述、token 是另一系统生成的复合 id 时。

## Discriminator
第一次真实数据可行性探针的输出行里，token 的真实取值就已可见（如 'pattempt:292a6971e7f…' 自带冒号）——即真实记录按同一分隔符 split 的段数比规格串 <prefix>:<token>:<digest16> 描述的段数多一段。

## Short path
- 动手改解析前，对一条真实历史记录跑可行性探针（重算 digest 等），并显式核对探针输出中 token 的真实形态是否内嵌分隔符，而不是只消费探针被问的那个答案。
- 若 token 内嵌分隔符：解析改为锚定不变量——先剥已知前缀，再取定长尾段（如 digest16），中间整体作为 token；token 仍做模式/长度校验，未知前缀或异常形状 fail-closed。
- 单测种子复刻真实复合形状（含分隔符的 attempt id），使合成测试对段数漂移敏感，而非全部使用理想化三段形状。
- 以真实历史 root 的只读端到端核验收口，并保留篡改段数/前缀/digest 长度的负测，证明严格性未因兼容而降级。

## Stop conditions
- 解析对真实历史记录（含复合 id）与新格式记录端到端均通过且核验 aligned=true
- 负测证明未知前缀/异常段数/digest 长度不符仍然失败（fail-closed 语义未被削弱）

## Verification
- 用至少一条真实历史记录跑只读全链（解析→重算→比对），不能只依赖合成单测
- 检查测试集中存在与真实记录同形（复合 id 含分隔符）的种子，否则段数漂移不可测

## Counterexamples
- 规格 token 明确为纯 hex 且全部真实记录严格三段：固定段数校验本身是 fail-closed 资产，不应为通用性放宽
- 真实历史数据不可读或已归档删除：无从烟测，只能按规格实现并显式记录『未经真实形状验证』的假设
- 格式本身是结构化字段而非字符串拼接：不存在分隔符歧义问题，此法不适用
