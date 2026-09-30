---
method_id: multi-hop-client-state-test-localize-at-first-unproven-hop-4bdae8a23567
name: multi-hop-client-state-test-localize-at-first-unproven-hop
description: 修复由客户端状态跨边界定义的缺陷（登录 cookie 跨主机名、会话跨重定向、CSRF 跨 origin）后，回归测试应按 hop 边界分段断言：服务端 emit 状态标记 → 客户端 jar 存储 → 下一请求携带。当测试在后续 hop 失败时，不要整体重跑猜测或先改服务端，而是用同一次运行内已通过的断言证明哪一侧已无嫌疑，再对第一个未被证明的 hop 做一次插桩重跑（打印 jar 与实际出站 Cookie 头），只修被证据指认的一侧（测试装置 vs 服务端）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d8f59859-1341-4560-9f92-9163e49963d5:697:801c00dda100fe002cac
evidence_refs: learning:learn:c721db281c85
created_at: 2026-09-30T13:01:50.349521+08:00
updated_at: 2026-09-30T13:01:50.349521+08:00
---
## Trigger
为跨边界状态缺陷编写/调试多跳回归测试（如双主机名共享登录会话），测试在后续请求 hop 失败，而同一次运行中前序断言已通过（如 set-cookie 已含 domain=父域 后，兄弟主机名请求仍返回 303/401）。

## Discriminator
同一次运行内的证据可二分责任：已通过的 set-cookie/domain 断言证明服务端 emit 正确；后续 hop 被弹回只说明状态未被交付或未被接受。此时未知量是 cookie jar 的域匹配/secure-scheme/共享方式等测试装置语义，而非服务端逻辑——该事实在失败回执的断言上下文中当时即可见，无需改服务端代码。

## Short path
- 测试设计时在每个 hop 边界放独立断言：响应头含状态标记；客户端 jar 已存该 cookie（含 domain/secure 属性）；下一请求将携带它
- 失败时先列出本次运行已通过的断言，圈出第一个未被证明的 hop
- 对该 hop 做一次插桩重跑：打印 client cookie jar 内容与实际出站 Cookie 头
- 只修证据指认的一侧：jar 共享方式/base_url scheme/域匹配属测试装置；仅当请求确实携带有效 cookie 仍被拒时才改服务端
- 全文件重跑，并保留旧行为对照测试（host-only 时兄弟主机名必须仍被弹回），防止回归测试退化为恒真

## Stop conditions
- 原失败断言在未改动服务端代码的情况下转绿（装置修复完成）
- 出站请求被证明携带有效 cookie 而服务端仍拒绝 → 转入服务端修复
- 旧行为对照测试不再按设计失败/通过 → 测试失去鉴别力，先修测试再谈行为

## Verification
- 全套测试绿，且同时包含旧行为复现与新行为断言两个方向
- 事故关键断言（set-cookie 含 domain=父域）未被删除或弱化
- 测试场景与真实拓扑一致：两个主机名、同一 origin、共享 cookie jar 模拟同一浏览器

## Counterexamples
- set-cookie 头本身缺少 Domain 属性 → 服务端缺陷，勿怀疑测试装置，本方法不适用
- 单请求单元测试失败（无跨请求状态）→ 常规断言调试，本方法多余
- 测试显式手工注入 Cookie 头、不经 jar → jar 语义无关，方法不适用
- 同次运行内前序断言也失败 → 服务端 emit 未被证明，二分前提不成立，先修服务端
