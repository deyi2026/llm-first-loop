---
method_id: pid-bound-endpoint-probe-for-redeployed-service-readback-995646b451f3
name: pid-bound-endpoint-probe-for-redeployed-service-readback
description: 受管服务部署/重启收敛后做 HTTP 回读验证时，先绑定再探测：以权威部署回执给出的活 pid 解析其监听 socket，只在该端口探测目标路径；响应先 dump 实际 key 结构，按观察到的嵌套取字段。未绑定 pid 的 404/200/字段全空无法区分『路径错』与『打到了旧实例』——记忆端口是过期坐标，旧实例曾让先前的探测拿到假结果。适用于多实例并存主机的部署后验证。
aliases: 404不一定是路径错, curl打到旧进程, 用lsof按pid查监听端口, 重启后服务换了端口怎么验证, 字段全是None先看结构, 别用记住的端口探测
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:d0e6ba0c-dfdb-4a7e-b110-850f0ae238a6:1024:f1eb5224bb7ccc5a4ce4
evidence_refs: learning:learn:5a697f170bdb
created_at: 2026-11-05T12:57:57.935386+08:00
updated_at: 2026-11-05T12:57:57.935386+08:00
---
## Trigger
受管部署/重启刚收敛（回执已确认 pid/head/generation），需经 HTTP 验证服务可观察面（board/状态页/api），而主机上同服务可能并存旧实例或残留监听端口

## Discriminator
权威部署回执已给出活进程身份（pid+generation+head）；任何未绑定到该 pid 的端点响应（404/200/字段全 None）都无法区分『路径/前缀错』与『打到了旧实例』—— remembered 端口是过期坐标

## Short path
- 从部署回执取活 pid，用 lsof 按 pid 解析其监听 socket（地址+端口），不猜、不沿用记忆端口
- 只在该 socket 上探测目标路径；此处的 404 才真正指向路径/前缀问题，再去查路由定义
- 响应先一次性 dump 实际 key 结构（顶层键+嵌套位置），按观察到的嵌套提取字段，不按假设 schema
- 将响应中的 sha/generation/in_sync 与回执逐字交叉核对，一致即停，不再追加确认性探测

## Stop conditions
- pid 绑定端点上取得的权威标识（head/generation/in_sync/source）与部署回执一致
- 同主机其他监听进程已识别并排除，不再引用旧端口

## Verification
- socket 归属的 pid 与回执 pid 一致（lsof 输出直接对账）
- 响应内 deployed_sha/generation 与回执逐字一致，数据源标注为权威回执而非人工台账
- 若响应字段读出 None：先核对实际 key 嵌套，确认是提取路径错还是真缺失

## Counterexamples
- 单实例主机、端口稳定且有文档约定：直接探测已知 URL 即可，pid 解析是多余开销
- 部署回执本身已携带 base_url/port：直接使用，无需 lsof
- 只有外部 URL、无 shell/socket 权限：无法绑定 pid，只能靠响应内嵌标识（sha/build id）归因实例
