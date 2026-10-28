---
method_id: char-offset-bisect-hydration-on-truncated-singleline-json-receipt-2446d8264426
name: char-offset-bisect-hydration-on-truncated-singleline-json-receipt
description: 工具回执是单行大 JSON（如 service status 快照）、显示在数组中段被截断、而裁决所需字段（各 target 的 idle_state/barriers/generation）位于未显示部分时：寻址模式先于通道选择——从截断显示本身即可判定单行（全程无换行），行号范围必返回 count:1 无法移动窗口；直接对 evidence blob 做字符偏移水合：先尾部探测定总长上界，再向锚点字段名定点/二分，读到全部裁决合取字段即按授权条款一次性裁决并停。与 bounded-span 重读卡不同：那张针对早前已完整读取过的文件重取，本卡针对从未被完整显示过的工具观测做恢复导航。
aliases: 状态输出截断了怎么把字段读全, 单行JSON截断补读, 回执截断后按字符偏移找字段, evidence水合二分读大JSON, 截断快照里确认web忙不忙
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0a37a89a-ded5-4f58-8502-1934aeaf0919:45:a7e0981a4b31bca595b0
evidence_refs: learning:learn:b54c959a60b2
created_at: 2026-10-24T17:53:07.096667+08:00
updated_at: 2026-10-24T17:53:07.096667+08:00
---
## Trigger
受管服务 status/快照类工具回执为单行大 JSON，显示被截断在中段（如截在 generation_lag 数组内），而验收/裁决所需合取字段位于未显示尾部；回执带 evidence ref 且支持带 count/complete 元数据的范围水合

## Discriminator
截断显示本身可见整份 JSON 无任何换行 ⇒ 单行 blob ⇒ 任何行号范围必返回 count:1、窗口无法移动（此判定在水合前即可从首次回执做出，无需试错）；同时 evidence 检索命中片段已含锚点字段名（如 idle_state/confirmed_idle/…ed_busy）证明所需字段确实存在于下游，只需字符偏移即可到达：尾部探测 count:0+complete:true 给出长度上界，再向锚点定点/二分

## Short path
- 一次只读 status 取观测，记录截断点与 evidence ref；未知量=所需裁决字段（web/feishu/learning idle_state、barriers、generation）的值
- 用 evidence 检索命中确认锚点字段存在于 blob 并取邻近片段，不做全 blob 重取
- 从首次显示判单行 ⇒ 跳过 line 范围水合与 shell 探测等无效通道，直接 text_char 尾部探测（count:0 + complete:true）定总长上界
- 向锚点字段名定点/二分字符范围读取，直到各 target idle_state、barriers、generation 全部读到
- 各段同 blob_sha256 且字段齐备 ⇒ 按授权条款一次性裁决：confirmed_busy 属确定性否定 ⇒ 不调 update、不重试前置检查，停并报告（含 active run lock 归因与下次 run 需重验 CAS 的提示）

## Stop conditions
- 全部裁决合取字段已从同一 evidence blob 读到，且与截断前缀同源（blob_sha256/range_sha256 一致）
- 尾部探测 count:0 且 complete:true 而锚点字段仍不可达 ⇒ 停止水合，改走工具侧过滤参数或重新调用工具
- 读到确定性否定（如 web confirmed_busy）即按授权停：不发起 mutating 调用、不做第二次 update 前置检查

## Verification
- 各次水合回执 blob_sha256 一致，range 的 count/complete 与请求窗口自洽（count:0 ⇒ 已过末端）
- 读到的字段值与检索命中片段互相印证（如 feishu confirmed_idle 片段一致）
- 最终裁决只依赖已读字段，未把截断前缀中未出现的字段当作默认值或推断值

## Counterexamples
- 多行 pretty-printed JSON：行范围有效，直接按行号窗口读，不必字符二分
- 工具支持过滤/summary 参数，或可用 jq/Python 一次抽取字段：一次调用优于多次范围水合
- 裁决需要实时现值而 blob freshness=unknown/currentness=unverified：水合只恢复'当次观测'，需现值应重新调用工具
- 无 range 寻址元数据的回执：不可导航，重新请求更小输出而非猜测未显示内容
