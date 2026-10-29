---
method_id: post-restart-liveness-via-live-observables-not-append-only-log-17d2e3097226
name: post-restart-liveness-via-live-observables-not-append-only-log
description: 崩溃后重启的常驻服务，其 nohup 日志是同一份 append-only 未截断文件：旧 traceback 会永远留在 tail 里反复出现，而连接建立事件可能根本不写日志，所以重读日志尾回答不了『现在健康吗/长连接建立了吗』。判据：重启回执里新 PID 已存活，且日志中旧 traceback 之后出现了本次启动成功行（如 post-manifest 成功行），即启动已通过、traceback 属于历史。当前状态问题改用活跃状态量一次探测：该 PID 的 ESTAB socket（对照配置声明的远端）、心跳/状态文件 mtime。防止把日志残留的 traceback 误判为二次崩溃，也防止反复 tail 等新行或用『日志安静』推断未连接。
aliases: 重启后日志还是旧报错能信吗, 怎么看服务到底连上没, 用 ss 看长连接代替翻日志, tail 日志判断不了服务存活, 心跳文件判断服务活着, 日志残留 traceback 不是新崩溃
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1743:2014580cd7c43e8bab26
evidence_refs: learning:learn:8a00bb446744
created_at: 2026-10-29T20:46:23.066430+08:00
updated_at: 2026-10-29T20:46:23.066430+08:00
---
## Trigger
常驻服务（如消息桥/边车）崩溃后被重启，日志为同一份 append-only 未截断文件（nohup 追加），需要回答的是现时状态问题：服务现在是否健康、对外长连接现在是否建立。

## Discriminator
重启回执同时给出两个可判事实：(1) 新 PID 出现在进程表且存活；(2) 同一日志 tail 中，旧 traceback 之后已经出现本次启动成功行（write_manifest 之后的 manifest/启动成功行）。traceback 位于成功行之前即为历史残留；append-only 结构决定了它之后每次 tail 都还会出现。

## Short path
- 读日志拿 traceback 定位崩溃根因——历史问题，日志才是权威源
- 修复式重启后，只从重启回执判定『启动是否通过』：新 PID 存活 + 旧 traceback 之后出现本次启动成功行，即已回答
- 若剩余未知量是『当前对外连接/运行状态』：直接探测活跃状态量——该 PID 的 ESTAB socket（对照配置中声明的远端:端口）+ 心跳/状态文件 mtime
- 活跃状态证据到手即停止，不再回头 tail 同一份日志等新行
- 仅当活跃探测显示无连接/无心跳时，才回到日志或源码找新原因

## Stop conditions
- 已从活跃状态证据确认当前健康：ESTAB 远端与配置一致、心跳文件 mtime 在预期周期内
- 活跃探测为阴性（无连接/心跳停滞）才升级为新一轮诊断

## Verification
- ESTAB 连接的远端地址:端口与该服务配置声明的远端一致，不能只看『有连接』
- 心跳/状态文件的 mtime 落在服务声明的心跳周期内
- 若要下『又崩了』的结论，必须先确认该 traceback 位于本次启动时间之后（位置/时间戳），而非日志残留

## Counterexamples
- 日志按启动轮转或每次截断、或服务专门记录连接事件日志——此时读启动后的新日志行就是正确探针，无需 socket 探测
- 问题是『当时为什么崩』——历史诊断，日志 traceback 才是权威，活跃状态答不了
- 远端地址不固定且配置未声明目标——先读配置确定预期远端，否则『有 ESTAB』不能等同『连对了』
- 运行环境看不到进程 socket（无 /proc、ss/lsof 不可用）——退回进程存活 + 文件系统状态量（心跳文件）
