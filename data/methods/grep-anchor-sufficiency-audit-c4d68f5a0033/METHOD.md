---
method_id: grep-anchor-sufficiency-audit-c4d68f5a0033
name: grep-anchor-sufficiency-audit
description: 核对多个具名符号/事件口径（产生点、字段语义、消费点）时：每个符号只做一次定向 grep，其输出中的 file:line 锚点与类型定义行即为后续全部读取的唯一驱动。字段语义类未知量（如 0 与未上报是否可分）由 grep 已暴露的 dataclass 定义行（int=0 不可区分 vs int|None=None 可区分）直接作答；不再对已看过输出的符号重跑子集 grep 做再确认。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d8f3d445-6e86-457c-bf7f-b10c1665f75e:130:e03854f45423ddc31f1d
evidence_refs: learning:learn:d4a154554b04
created_at: 2026-09-22T16:56:01.310261+00:00
updated_at: 2026-09-22T16:56:01.310261+00:00
---
## Trigger
需要在代码库中审计 N 个具名符号（事件/指标）的 provenance——产生位置、字段语义、消费链路，且符号名已被用户或上游明确点名。

## Discriminator
首次 per-symbol grep 的可见输出是否已同时给出关键命中锚点（定义行+解析赋值行+消费行）与类型默认值；若两者已在手，任何同符号子集 grep 或生产→消费链之外的相邻代码阅读都不再缩小任何未知量。

## Short path
- 对每个具名符号各执行一次定向 grep，收集产生点、定义、消费点的 file:line 锚点
- 只按锚点读各符号的产生点代码段，确认字段来源（如 resp.prompt_cache_hit_tokens）
- 语义未知量（0 vs 未上报）直接由 grep 已暴露的类型定义行作答：default=0 不可区分、default=None 可区分
- 沿生产→末端消费链读收尾/持久化处签名，确认字段透传完整
- 每个符号三要素（产生点/语义/消费点）齐备即停，转入写测试；不重跑已看过输出的子集 grep

## Stop conditions
- 每个具名符号均已取得：产生点锚点、定义语义（默认值能否区分未上报）、末端消费点
- 字段语义已由定义行与解析赋值路径双向印证（default 与赋值逻辑一致）
- 所有结论均可回指到具体 grep 命中行号

## Verification
- 逐条检查最终结论是否都能引用到某次 grep 输出中的具体行号
- 检查调用序列中不存在对已完整查看输出的符号再跑子集 grep 的重复调用
- 确认读取的每个代码段都位于该符号的生产→消费链上，无链路外阅读

## Counterexamples
- grep 输出被 head 截断（如仅显示前 17/20 行）且无法确认枚举完整时，补跑更窄的 grep 是正当的，不应套用本方法拒绝补查
- 运行时行为可能与源码定义不一致（monkey-patch、post-init 改默认值、多版本 schema）时，类型定义行不足以判定语义，需真实运行或测试取证
- 符号名在库中高度重载、跨 10+ 文件且语义各异时，单次 grep 锚点不足以定位，需按模块分层收窄而非一次定位
