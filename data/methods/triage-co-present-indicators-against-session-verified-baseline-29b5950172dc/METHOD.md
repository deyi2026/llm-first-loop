---
method_id: triage-co-present-indicators-against-session-verified-baseline-29b5950172dc
name: triage-co-present-indicators-against-session-verified-baseline
description: 当一次状态快照同时暴露多个独立指标，且某子系统在本 session 已有权威健康证据（如 /health ok:true）时，先对全部指标做 triage 排序再深挖：已验证健康子系统上的瞬态 boot/重试指示（带 try 计数）降级；未被验证、指向用户报告故障域的稳态指标优先。先用一次廉价判别实验（换访问路径重查状态，如经 localhost 直开页面）分离候选子系统，收敛后再做配置级调查与最小修复。根因必须同时解释全部指标；被降级指标须在无干预下自行消散，否则返回 triage。避免对最显眼症状直接做 i18n/前端 bundle 源码级深挖。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:97877415-9ecf-4ec7-840e-a4568f1f55ed:26:1bf461ccd218ef8843d8
evidence_refs: learning:learn:13e211dff1e9
created_at: 2026-10-06T21:25:53.552116+08:00
updated_at: 2026-10-06T21:25:53.552116+08:00
---
## Trigger
诊断任务中，同一观察面（顶栏/状态页快照）同时呈现多个独立状态指标；其中一个所属子系统已被本 session 更早的权威检查（/health 200 ok:true）验证健康，另一个稳态指标指向用户报告的故障域但尚未解释；模型正准备深挖其中第一个/最显眼的指标。

## Discriminator
首个 AXTREE 快照同屏给出两个指标：(1) Status: Offline + 'Aligning local access token… (try 5)'——带 try 计数的 boot 重试指示，属瞬态设计，且其子系统（127.0.0.1:8790 本地服务）在本 session 早前 /health 已返回 ok:true；(2) 'Public tunnel: Tun—'——稳态隧道状态异常，正对应用户报告的公网入口故障域且无既有解释。当时即可据此把调查优先级给到隧道分支，无需先解析本地令牌路径。

## Short path
- 列出快照中全部独立指标，逐个标注所属子系统与本 session 已有验证事实（/health ok:true → 本地服务已验证健康）。
- 排序：已验证健康子系统上的瞬态重试指示降级；未验证且指向用户故障域的稳态异常优先。
- 做一次廉价判别实验分离分支：不经隧道、经 localhost 直接重开页面并重读状态。
- 若本地变 Ready 而隧道指标仍异常 → 收敛到隧道分支：读权威配置（launchd plist / cloudflared 配置），对比 --edge-bind-address 与当前网卡 IP。
- 最小修复（改绑定 IP + bootout/bootstrap 重载），验证隧道 conns 0→2 且公网 /health 200 后停止。

## Stop conditions
- 单一已验证根因同时解释全部指标，且端到端权威检查全绿（隧道边缘连接数>0、公网 /health 200）。
- 廉价判别实验结果与排序矛盾（被降级指示不随 boot 消散，或本地路径也异常）→ 立即切换分支，不做源码级深挖。

## Verification
- 根因必须同时解释 Offline/对齐令牌 与 隧道异常 两个指标；只解释其一时回到 triage，而非继续在原分支深挖。
- 确认被降级分支的指示在无专门干预下自行消散（本地页面自行变 Ready）；否则降级判定错误，需重排优先级。

## Counterexamples
- 观察面只暴露单一指标、无可对照的第二个稳态指标时：无法 triage，直接深挖该唯一症状。
- '已验证健康'证据过期或指向不同实例/端口/版本（如 /health 属另一进程）时：必须先重验 baseline，排序不可迁移。
- boot 指示无 try 计数、跨重载持续存在，或 try 计数无界增长时：它已是稳态故障，不因属于健康子系统而降级。
