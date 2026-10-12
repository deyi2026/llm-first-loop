---
method_id: resolve-self-owned-service-endpoint-from-declared-source-not-port-scan-d8c741db314e
name: resolve-self-owned-service-endpoint-from-declared-source-not-port-scan
description: 定位一个自己拥有、可读其内部状态的服务入口时，先读该服务自身声明/记录该属性的来源（部署或重启 receipt、控制配置、运行日志里打印的 URL），只对该声明入口做一次可达性验证并按服务语义解读状态码；只有当声明缺失或过期时，才用已取得的 LISTEN 端口集合作为有限上界收窄候选。不要对常用端口×常用路由做笛卡尔积探测，也不要在同一条回执已经给出监听端口全集后继续猜集合外的端口。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:1834:89a652d7b01dfaa338d0
evidence_refs: learning:learn:1ed4247f3396
created_at: 2026-09-18T07:19:39.245334+00:00
updated_at: 2026-09-18T07:19:39.245334+00:00
---
## Trigger
需要确认一个自己控制/本机部署的运行中服务的实际入口地址（端口或路径），或确认其某个可自述属性是否生效

## Discriminator
同一工具回执里 lsof 已经列出全部 LISTEN 端口（8765/8768/8903…），'哪些端口可能应答'当时已有权威且有限的答案；而探针仍在打集合外的 8766/8000/8080，注定连接失败。同时该服务所属仓库内可读的启动配置与 data/*.log 会直接声明真实入口 URL。缺的不是更多探测，而是读取已存在的自述来源。

## Short path
- 先看部署/重启终态与版本（gen19、rc=0），确认服务确实在运行——未知量：进程是否活着
- 在服务自身的日志或启动/控制配置里取它声明的入口 URL/端口（data/web.log 打印 http://127.0.0.1:8903）——未知量：服务自称入口是什么
- 只对该声明入口做一次可达性探测，并按服务语义解读状态码（303 重定向=真入口，根路径 404=正常）
- 用日志 mtime 是否持续推进确认它在处理请求，而不只是占用端口
- 仅当声明来源缺失或过期时，才退回到已取得的 LISTEN 集合作候选上界，仍不从常用端口表盲猜

## Stop conditions
- 已从服务自述来源取得唯一入口，并探测到非连接失败的响应
- 已用推进中的日志写入证明服务在处理请求

## Verification
- 入口返回码与日志/配置中记录的入口一致（如 8903 返回 303）
- 探测时刻服务日志的 mtime 仍在推进
- 实际探测过的端口集合是 LISTEN 集合的子集

## Counterexamples
- 目标是第三方/外部服务，不提供自述日志或配置，端口扫描是唯一可得手段
- 任务本身就是端口暴露面/安全审计，穷举扫描是目标而非浪费
- 自述来源已过期（配置指向旧端口而进程已换端口），必须用 LISTEN 集合或真实 socket 归属做交叉验证
