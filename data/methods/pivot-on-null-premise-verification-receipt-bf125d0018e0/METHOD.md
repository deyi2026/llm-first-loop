---
method_id: pivot-on-null-premise-verification-receipt-bf125d0018e0
name: pivot-on-null-premise-verification-receipt
description: 当一次调用的参数本身编码了一个具体前提——猜测的规范名（如 openJiuwen-ai/openJiuwen 仓库路径）或假定的实体归属对（如「第四范式 HiAgent」）——而回执为空/噪声（关键字段全 None、关键实体零命中、或与先前宽搜索返回同一结果集）时，把空回执当作对前提本身的裁决，而非搜索质量问题。不要换同义词重试同类宽查询；改走已可见或可直接导出的最窄权威一跳：同名 API 的 org/namespace 列表，或对实体单独查询确认归属。既避免重复宽搜索，也避免未验证前提渗入分析稿、最后在交付信息里被迫公开自我更正。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:40eeca85-e561-4f26-9faf-efda5823cb4b:8:db4fd27c7f2d787adfbd
evidence_refs: learning:learn:a42132867150
created_at: 2026-10-10T14:26:29.413177+08:00
updated_at: 2026-10-10T14:26:29.413177+08:00
---
## Trigger
一次为验证某前提而发起的调用（猜测的 GitHub 仓库/org 路径、假定的「厂商+产品」配对查询）返回空或噪声回执：关键字段全为 None、结果片段中关键实体零命中，或与上一次宽搜索的结果集完全相同。

## Discriminator
回执可机械核验，且当时已可见：(a) 回执既不含前提关键实体也无新信息——repo API 对 openJiuwen-ai/openJiuwen 返回全 None，而更早的搜索结果已显示真实 org 地址 github.com/openJiuwen-ai/；「第四范式 HiAgent」查询只返回字典噪声，且此前所有回执中从未出现任何支持 HiAgent~第四范式配对的条目；(b) 相邻两次宽搜索返回完全相同的 8 条结果，证明第二次无新信息。空回执 + 已有更窄权威句柄 ⇒ 判前提、转向窄一跳。

## Short path
- 照计划发起编码前提的调用（repo API / 配对查询）。
- 机械读回执：是否包含前提的关键实体？是否带来任何新信息？
- 若空/噪声：先把该前提标记为未验证；取先前回执中已显示的最窄权威句柄（org URL → 同 API 的 org 仓库列表；配对无任何支持回执 → 对实体单独查询确认归属），一次调用解决真正未知量。
- 用新回执修正名称/归属后再回到原分析计划；归属修正须依据直接条目（如「HiAgent 是字节跳动火山引擎推出的平台」）。
- 凡进入交付稿的实体-属性断言，必须能指到一条包含该配对的回执，否则显式标注[未验证]。

## Stop conditions
- 窄一跳回执返回权威数据（org 仓库列表、实体归属条目），原未知量已解决。
- 待写断言均有支持回执，无未验证前提残留。

## Verification
- 对成稿做实体-属性断言清点：每条都能溯源到一条包含该配对的回执（本集本应先取得第 8 步『字节跳动火山引擎』条目，才允许 HiAgent 归属入稿，避免最终消息里的公开自我更正）。
- 比对同 backend 相邻两次宽搜索的结果集；完全相同（第 1、4 次搜索同一批 8 条）即证明第二次是冗余调用，应在 org API 一跳处转向。

## Counterexamples
- 宽查询返回部分相关结果：属正常迭代检索，空回执裁决不适用，不应过度转向。
- 回执明示瞬态失败（timeout/429/限流）：应重试原调用，而不是改判前提为假。
- 某些 API 对不存在资源返回 200+空对象、对配额问题也返回空字段：需先核对该 API 的 not-found 语义，再决定把全 None 读作证伪。
- 窄句柄不存在且实体确实冷门（如 org 本身不存在，org API 直接 404）：此时宽搜索/目录发现才是正确动作，不应强行对不存在实体做直接查询。
