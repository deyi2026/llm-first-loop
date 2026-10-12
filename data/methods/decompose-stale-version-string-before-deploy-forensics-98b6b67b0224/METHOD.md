---
method_id: decompose-stale-version-string-before-deploy-forensics-98b6b67b0224
name: decompose-stale-version-string-before-deploy-forensics
description: 用户报告'版本号一直没更新'时，先把版本串当结构化工件拆解（基础版本、-dev 计数、+g 提交哈希），定位渲染该串的代码确认各成分来源，再决定是否做部署取证。串内嵌的提交哈希与运行进程/仓库 HEAD 的一致性可一步区分'环境跑旧代码'与'版本元数据未推进'；持续增长的 -dev 计数通常意味着发布动作（版本文件 bump+打 tag）缺位，而非显示 bug；若显示在进程启动时计算一次，修复还需重启才生效。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:2254:34f8cb7ba298ddf65489
evidence_refs: learning:learn:409c75a83be5
created_at: 2026-09-24T04:33:17.703576+00:00
updated_at: 2026-09-24T04:33:17.703576+00:00
---
## Trigger
用户报告某版本/构建标识'一直没更新/不动'，且该标识是复合串（含基础版本号、计数后缀、提交哈希等可分解成分），病因可能在部署陈旧或元数据未推进之间二选一

## Discriminator
串内嵌的提交哈希（如 +g<short-hash>）与运行进程/仓库 HEAD 的比对：一致 → 运行代码是新的，'不更新'的是版本元数据源（版本文件/tag 未随变更日志推进）；明显落后 → 才是部署陈旧。此事实在拆开串的一刻即已可见，无需先做进程/端口/代次取证

## Short path
- 拆解被报告的版本串，明确用户所指'不更新'的是哪个成分（基础版本号而非哈希——哈希和计数其实在变）
- grep 定位组装/渲染该串的代码，读出各成分来源：基础版本←版本文件、计数←距最近 v* tag 提交数、哈希←HEAD
- 双比对闭合两个未知量：串内哈希 vs 仓库 HEAD（代码新旧）；版本文件&最新 tag vs 变更日志最新条目（发布动作是否缺位）
- 若为发布缺位：执行项目发布三件套（版本文件 bump + 打 tag + 变更日志条目），历史版本不追溯补 tag；不改显示代码
- 重算标识验证（如 release_exact=True、距 tag 计数归零），确认显示是否启动时算一次 → 受理重启/重部署后停止

## Stop conditions
- 成分→来源映射已核实且根因已命名：代码新旧与元数据推进两个未知量均闭合
- 修复后重算标识得到精确值（release_exact=True），而非仅改了文件
- 显示若在进程启动时计算一次，重启/重部署已受理并有终态核对入口

## Verification
- bump+tag 后重跑 build/display 计算，确认精确匹配（release_exact=True、计数=0）
- 修复前后均确认串内哈希与实际运行 HEAD 的关系，防止把'元数据未推进'误判为'部署陈旧'或反之
- 确认显示消费点是否缓存于启动（如仅在 write_manifest 计算一次），据此判断是否必须重启

## Counterexamples
- 版本串是无内嵌哈希的裸常量（硬编码 'v1.0'）→ 拆解无信息量，应先做部署/缓存取证
- 串内哈希确实落后于仓库 HEAD（CDN/流水线没发布）→ 判别器指向部署陈旧，应排查部署链路而非 bump 版本，否则会把未发布的代码误标为已发布
- 显示逻辑本身损坏或被缓存到重启也不变 → 补发布动作无效，须先验证显示消费点与缓存时机再下结论
