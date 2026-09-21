---
method_id: probe-attach-target-endpoint-before-automation-717ea9067afe
name: probe-attach-target-endpoint-before-automation
description: attach 类任务（操作用户已启动的外部实例，如带调试端口的浏览器）中，先用最原始工具直接探测目标实例的控制端点（如 CDP /json/version），以最廉价方式确认可达性、实例身份与可用驱动，再据此选自动化通道；同时把工具 schema 中的硬约束（URL 白名单、隔离会话、禁裸 import）当作通道判别器——结构上不支持的通道直接排除，不在其上试跑。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:103:4621a7766be119a6502d
evidence_refs: learning:learn:0d4553a594b0
created_at: 2026-09-20T08:44:37.288078+00:00
updated_at: 2026-09-20T08:44:37.288078+00:00
---
## Trigger
任务前提是连接并操作一个已启动的外部实例（用户表示'已启动好'），需 attach 后读取/操作，但实例可达性与自动化通道均未验证。

## Discriminator
任务前提本身（用户已自行启动实例待连接）蕴含存在一个可探测的控制端点（调试端口），用原始 HTTP 探测即可验证，且与选哪个自动化工具无关；此外工具 schema 明示其浏览器为隔离实例且 goto 有 URL 白名单，即该通道结构上无法 attach 外部实例——这些事实在试跑前已可得。

## Short path
- 明确未知量：目标实例是否可达、经什么通道连接
- 用最原始工具一步探测：GET 控制端点（如 http://127.0.0.1:9222/json/version）+ 检查执行环境驱动库可用性
- 探测成功 → 用已确认的通道（CDP attach）列出标签页，验证连的是用户真实实例
- 在同一 attach 会话中导航到目标（如 Gmail）并提取所需状态
- 目标事实（未读数/最新邮件）已取得即停止，不再扩展操作

## Stop conditions
- 已通过确认可达的通道 attach 并取得用户所需事实，立即停止
- 控制端点探测失败（连接拒绝/超时）→ 不再尝试依赖该实例的自动化，直接报告实例未就绪

## Verification
- attach 证据：列出的标签页包含用户当前真实会话内容（如用户正打开的页面），而非工具自带隔离浏览器的空白页
- 探测到的浏览器版本/端口与实际连接会话一致，最终数据来自同一 attach 连接

## Counterexamples
- 目标站点在预置 helper 的 URL 白名单内且无需用户实例登录态 → 直接用 helper goto，端点探测是多余开销
- 用户未预先启动任何实例，任务是从零启动并自动化浏览器 → 无 attach 前提，不适用本方法
- 已掌握当前工具完整 schema 且其明确支持 attach 外部实例 → 跳过探测，直接连接
