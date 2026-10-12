---
method_id: close-channel-on-deterministic-self-describing-failure-36bd486e20c1
name: close-channel-on-deterministic-self-describing-failure
description: 跨通道取内容时，若某通道的首次响应本身是确定性且自述成因的——错误信息自己枚举根因（如 CDP exactly-one-page…observed=3 且无 target_id 口子）、空壳页证明内容只存在于客户端、或含完整品名的查询返回品牌首页级无关结果集——则该通道对本任务关闭：不再换措辞查询、不再试同族 URL 变体、不再换调用形态打同一坏环境。同时把 artifact 自述的消费通道（分享文案写明「App 内打开/淘宝搜索」）当零成本先验：它预言哪些 web 通道必死，各验证一次取证即可。之后转向未试过的通道类，或输出已关闭通道清单、恢复前提与用户侧替代方案。与『退化评审工具重试预算』方法相邻但触发域不同：那针对评审工具退化输出，本方法针对多通道检索中的确定性通道失败。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ca02bdc1-1ca9-4389-9732-e3ba796f5550:4:5f6d7e7ab7fcf519f4e8
evidence_refs: learning:learn:13efe0e163cc
created_at: 2026-10-07T17:19:41.418135+08:00
updated_at: 2026-10-07T17:19:41.418135+08:00
---
## Trigger
在多个通道（直接抓取/搜索引擎/宿主浏览器/沙箱浏览器）间检索某内容且通道未全部试过时；尤其当分享文本或链接自述了预期消费通道（如 App 接管的短链）。

## Discriminator
重试前已可见的四条事实：(1) 分享文案写「或者淘宝搜索直接打开」——链接自述由 App 接管；(2) 首个 web_fetch 返回无文本空壳页（纯客户端跳转）；(3) 首个含完整品名的搜索返回全部品牌首页级、零 SKU 相关结果；(4) CDP 错误自述确定性成因（exactly one page…observed=3）且注明接口无 target_id，非瞬态。每条都足以关闭一个通道或终止同类重采样。

## Short path
- 先读 artifact 自述：「淘宝搜索直接打开」表明短链由 App 接管；把 web 通道预期为空壳/登录墙，仍各验证一次取证
- web_fetch 短链一次→空壳页；结论：该链接家族无服务端可读入口，不再试 m.tb.cn 等同族变体
- 搜索一次（完整品名）→结果集全为品牌首页级；结论：搜索后端解析不了该长尾 SKU，停止换措辞重试
- 浏览器一次→CDP 错误自述成因（observed=3、无 target_id 口子）；结论：本会话内任何调用形态都无法改变该数，通道关闭
- 汇总已关闭通道，输出如实失败报告并列恢复前提与用户侧替代方案，停止

## Stop conditions
- 已从与 artifact 自述通道一致的来源取得目标内容
- 每个可调用通道类都恰有一次自述成因的失败记录且无新通道类可试——立即输出关闭清单+恢复前提+替代方案，不再采样
- 任一通道返回与目标结构相关的新证据（SKU 页、可抓取 endpoint、错误变为非确定性）——重新打开该通道

## Verification
- 每条通道关闭结论都能引用当时的原始回执（空壳 extract、错误原文、结果集构成），满足 knowledge-at-time，不靠事后推断
- 自查 trace：同一通道类没有第二次仅参数不同的调用（换词查询/同族短链变体/同错误再调用）
- 失败报告区分『目标客观不可达的原因』与『本环境自身缺陷』，分开记账不混写

## Counterexamples
- 首次搜索结果只是排序差但已含 SKU 相关条目——换一次措辞重试合理，不应关闭通道
- 错误是 transient timeout/限流——成因非确定性，应按退避重试，本方法不适用
- 空壳页显式引用 hydration script 或可抓取的 API endpoint——应沿该 provenance edge 取证，而非关闭通道
- artifact 未自述消费通道且首次失败原因不明——先做一次诊断性区分（输入触发 vs 通道坏），再决定是否关闭
