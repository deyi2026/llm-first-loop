---
method_id: one-shot-credential-state-ask-the-gate-not-side-surfaces-ef5598625db6
name: one-shot-credential-state-ask-the-gate-not-side-surfaces
description: 特权动作（push/publish/全量测试）被一次性审查资格门控，且资格按 schema 存于签发方内存、自述PASS/任意JSON/旧回执均无效时，"资格是否仍有效"这一未知量只能由闸门工具自身裁决：直接 start（命中复用窗口即秒回真实 child_id+PASS，未命中则冻结新审），再 status 领取一次性资格。不要用会话 evidence/归档检索、全盘 find、读闸门源码去"还原"资格状态——这些面按设计不是权威，miss 也不构成否定。受保护动作按闸门合同单段提交（workdir 参数，勿 cd/echo 复合），生效与否以后果权威面（远端 tip/部署代数）核验，异步未生效如实标注。
aliases: push 被拦说资格未核验怎么办, 审查资格还有效吗直接问准入工具, 别翻 evidence 找一次性审查资格, 资格存签发方内存去哪核验, 干跑 push 不能当资格凭据
status: candidate
source_model: deepseek/deepseek-flash
source_episode_refs: episode:4aea0dd4-3b3b-4874-8090-870678230df3:1359:02a811ade005285f9d8c
evidence_refs: learning:learn:e1cb55bc2515
created_at: 2026-11-03T16:56:17.832631+08:00
updated_at: 2026-11-03T16:56:17.832631+08:00
---
## Trigger
特权动作被一次性资格门控；此前存在"资格已签发"类断言但当前会话无可核验回执；或闸门横幅/回执显示"审查资格未核验"，需要先确定资格状态再行动。

## Discriminator
闸门工具 schema/规则文本（开局检索即可见）已声明：资格存于签发方内存、仅经 start/status 签发，自述PASS/任意JSON/旧回执/不同目标均无效——这按设计排除了 evidence、文件系统、源码作为验证面；且 start 带复用窗口缓存，直接调用廉价、有界，其回执本身就是权威裁决。

## Short path
- 一次取当前 git 事实（HEAD/分支/干净度/origin 基线）：资格绑定的就是这份内容身份。
- get_tool_schema 精确读闸门合同：查询路径、缓存/复用语义、受保护动作的命令形态约束。
- 以精确目标身份调用 start（kind/workdir/scope 按执行面推导）：cached_pass+真实 child_id ⇒ 资格本就存在；否则冻结新审。这一步单独解决"资格是否有效"。
- 对返回的 child_id 调 status 领取一次性 PASS 回执，核对其 candidate SHA/target 与当前树一致。
- 按合同单段执行受保护动作（workdir 参数，不与 cd/echo 复合）；若被命名 reason 拦截，reason 即合同差分，按其逐项修正重发。
- 后果权威面核验（远端 tip==本地 HEAD / 部署代数推进），异步未生效部分如实报告为 pending。

## Stop conditions
- 已取得一次性 PASS 回执，且其 artifact 身份（candidate SHA/target/kind）与待执行内容一致；
- 动作已在后果权威面核验生效（远端 tip==HEAD、publish 代数推进）；
- status 非 PASS 或 child 无终态 ⇒ 前置未满足，停止动作转修复，不得以任何旁证替代。

## Verification
- status 回执的 candidate_sha256 与当前树摘要、kind 与动作类型逐项一致；
- 动作后用 ls-remote（或部署 status）确认物理生效，而非依赖闸门横幅文本；
- 闸门横幅既非许可也非否证，一切以工具回执为准。

## Counterexamples
- 凭据是本地落盘的签名回执文件而非权威内存持有：文件系统检索才是正确验证面；
- start 无缓存且昂贵（每次触发数小时全量测试），而本会话已持有真实 child_id：直接调只读 status，勿重发 start；
- 某些系统查询即消耗一次性凭据：必须走非破坏性查询路径，不能用 start 当探针；
- 尚未识别出是哪个闸门在管该动作：schema/规则发现才是第一未知量，本方法前提是闸门已具名。
