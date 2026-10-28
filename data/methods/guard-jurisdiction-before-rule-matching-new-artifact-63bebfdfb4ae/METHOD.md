---
method_id: guard-jurisdiction-before-rule-matching-new-artifact-63bebfdfb4ae
name: guard-jurisdiction-before-rule-matching-new-artifact
description: 刚写完一个产物（收档文件/生成文件）就担心它触发某个守卫（提交安全扫描钩子、pre-commit、CI 内容检查）时，第一个未知量不是『内容是否命中规则』，而是『产物路径是否落在守卫的作用集内』（git 暂存区/跟踪树/CI 扫描面）。守卫配置里作用范围声明与规则同在：先一次有界定位产物落盘路径并与作用集比对，范围外即风险消解，无需再读规则细节或做内容模式匹配。
aliases: 新文件会不会被钩子拦, 先查扫描范围再查内容, 提交扫描管不管这个路径, 收档文件会不会触发脱敏钩子, 守卫作用域先于规则, 自查新写的文件算不算新暴露
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:5023:a0fb6899ea9064f21154
evidence_refs: learning:learn:2a2ce1d60e3a
created_at: 2026-10-27T22:38:13.651917+08:00
updated_at: 2026-10-27T22:38:13.651917+08:00
---
## Trigger
一次写入/收档动作刚成功，且担心该新产物可能触发已知守卫（security_scan 钩子、lint 门禁、CI 内容扫描），准备去读守卫规则或比对产物内容时

## Discriminator
守卫的作用范围声明（如扫描模式=--staged 暂存区 / --tree git ls-files，或钩子挂载的 repo/路径）+ 写入工具回执已给出的产物身份（ref/文件名）。两者都在查内容之前已可得：范围外时规则细节是无关信息

## Short path
- 把『产物落盘路径是否在守卫作用集内』定为第一未知量
- 用写入回执的 ref/文件名，在已知根（repo 根 vs 运行时工作区根）间做一次有界 find/ls 定位产物，不用宽 grep
- 比对路径与作用集（git 跟踪树/staged/CI 扫描面）：范围外 → 风险消解，收口并把该判据写进记录
- 仅当范围内，才读规则细节并逐条比对内容形式
- 停止：范围结论（必要时补一条内容不命中）写入收档记录即闭环

## Stop conditions
- 产物路径确定不在守卫扫描面（非跟踪、非 staged、不在 CI 作用域）
- 或产物在范围内且内容比对完成无命中（或命中已按守卫指引修复）

## Verification
- 用守卫自身的作用集定义复核：如 git ls-files / git diff --cached 不含该路径，或钩子脚本头部声明的输入模式
- 收档记录注明产物路径属性，供未来『产物被拷入 repo』场景追溯

## Counterexamples
- 产物确实写在守卫作用集内（直接写入 repo 跟踪目录或已 staged）→ 范围检查不能消解风险，必须做内容规则比对
- 守卫是全局/文件系统级（全盘 DLP、定时 grep 整个 HOME 的扫描器），没有『git 树』这类天然作用集 → 判据不成立，须直接读该扫描器配置与规则
- 担心的是产物将来被移动/拷贝进守卫范围 → 当下『范围外』只证明现在无风险，不是永久豁免，须在记录中注明边界条件
