---
method_id: behavior-lock-tests-derive-fixtures-from-callee-body-guards-73499161b3db
name: behavior-lock-tests-derive-fixtures-from-callee-body-guards
description: 为当前代码写行为锁定（回归钉死）测试时，fixture 形状与期望值以被测函数当前函数体为权威：写测试文件前先有界读取其输入守卫（校验早抛、精确 key 访问路径，如顶层 url 而非嵌套 page.url）、遍历/排序与谓词条件；签名、docstring、函数名或邻近 artifact 的同形结构都不是 fixture 依据。本集对照：8 个由已读构造签名/schema 导出的测试一次通过，3 个按名称/意图猜形状与期望的测试首轮全红，被迫回头读守卫（browser_page_url_unavailable@顶层 url）后才修补，多花一轮失败-诊断-修循环。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:2b31dcc4-fd74-4c8f-8057-a38edd911d3a:266:67151dc015366d760ae8
evidence_refs: learning:learn:0fc4222ebd94
created_at: 2026-10-20T16:20:58.462697+08:00
updated_at: 2026-10-20T16:20:58.462697+08:00
---
## Trigger
要为当前代码库中刚实现/刚修改的函数编写行为锁定（回归）测试，且部分被测目标只有签名/docstring/函数名在手、函数体（尤其守卫子句与返回构造）未读；或邻近模块存在相似数据结构（如浏览器语义投影 dict）易被误用作 fixture 形状。

## Discriminator
对每个被测函数问一个 knowledge-at-time 事实：其输入守卫（校验早抛、精确 key 访问路径）、遍历顺序、谓词条件是否已被读过？未读则 fixture 与期望处于猜测状态。本集恰成分层：已读构造签名/schema 的 8 个测试一次通过，只凭名称/意图写的 3 个全部失败在形状/顺序/谓词上。

## Short path
- 列出测试文件要锁定的每个行为点及其被测函数，标注哪些函数体已读、哪些只有签名/docstring
- 对每个函数体未读的目标做一次有界读取：守卫段+返回构造（grep/行号提取，不整文件重读）
- fixture 的 key 路径（顶层 vs 嵌套）、期望顺序、谓词期望逐条从函数体守卫与构造逻辑导出
- 写测试文件并首跑：此时仍失败应视为规格-vs-实现的真实分歧，显式决定改测试或改实现，而非形状笔误
- 定向回归+lint 一次收口

## Stop conditions
- 每个断言的 fixture 形状与期望值都能追溯到被测函数体的具体守卫/构造行
- 测试目的是独立规格（TDD 先红）时停止套用，改以规格为 oracle

## Verification
- 新测试文件首跑即全绿，或剩余失败均被显式归因为规格分歧并有改向决定
- 若有变更规格文本（如 EVO 建议/需求），交叉核对函数体与规格一致后再锁定，避免把实现 bug 钉死
- 定向回归与 lint 通过

## Counterexamples
- TDD/规格先行：测试本身就是独立 oracle，从实现体导出期望会锁死 bug、使测试失去检出力
- 验证对外契约（provider API/协议规范）符合性：外部规范才是 oracle，镜像本地实现会把偏差钉进回归
- 签名与 docstring 已完全确定行为的纯函数：预读函数体是纯开销，直接写测试更短
