---
method_id: user-named-attribute-first-scan-then-verify-before-destructive-cleanup-6cf59d34e364
name: user-named-attribute-first-scan-then-verify-before-destructive-cleanup
description: 对共享环境中与存活实例混居的资源做批量破坏性清理（杀进程/删目录），且用户已点名唯一可观察属性（如 profile 目录名、pytest 编号）时：第一次观察就按该属性收窄扫描（ps 用可移植关键字 command，勿用 Linux 专属 cmd），而不是先枚举整个应用类再人工过滤；从同一输出读取 PID 树/PPID/启动时间佐证孤儿身份；动手前用第二独立属性（根进程完整 cmdline 的 user-data-dir）核对；只对显式 PID 列表 SIGTERM，禁止按模式 pkill；事后双重核查：目标计数归零 + 受保护实例存活。收窄扫描为空或属性可能命中活跃会话时，才扩大枚举并要求更强生命周期证据，否则停手上报。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:96d621f5-1690-49cb-8e4d-e05d75600791:196:054a5f92c184d62f4375
evidence_refs: learning:learn:85d590857bb3
created_at: 2026-10-11T02:44:26.611456+08:00
updated_at: 2026-10-11T02:44:26.611456+08:00
---
## Trigger
即将对共享环境中与存活实例混居的候选资源执行批量破坏性操作（kill/清理），且用户消息已点名一个可用于区分目标与受保护实例的唯一可观察属性（子串/路径/编号）

## Discriminator
用户点名的属性（如 'e2e-profile'、'pytest-43/45'）在进程 cmdline/路径中唯一命中目标集合；同一 ps 输出的 PPID=1 与启动时间可佐证孤儿身份；受保护实例靠不同属性区分（自定义 profile 目录、调试端口、PPID≠1）。该属性在首扫之前已由用户消息给出，属 knowledge-at-time

## Short path
- 首扫即按用户点名属性收窄：ps -eo pid,ppid,lstart,command | grep '<attr>'（用 command 不用 cmd），一次取得目标 PID 树与孤儿证据
- 若扫描为空、有歧义或可能命中在跑会话，才扩大枚举并补生命周期证据（启动时间、锁文件、父进程状态）
- 动手前核对第二独立属性：读根进程完整 cmdline，确认 user-data-dir/路径与用户点名一致
- 对显式 PID 列表发 SIGTERM（勿按模式 pkill），随后复查目标属性计数=0 且受保护实例（如在用 profile 的实例）进程数/根进程不变

## Stop conditions
- 按目标属性重查计数为 0，且受保护实例存活、数量与操作前一致
- 首扫收窄结果为空，或与活跃会话重叠且无法用 PPID/启动时间/锁文件区分 -> 停手上报，不执行破坏性操作
- TERM 后复查仍有幸存者 -> 仅对幸存 PID 升级 SIGKILL 后再复查，不扩大打击面

## Verification
- 操作后按目标属性重查计数 = 0
- 受保护实例根进程/端口仍存活（重查其 profile 属性命中数与操作前一致）
- 被杀 PID 列表 ⊆ 已核对第二属性的树成员集合

## Counterexamples
- 用户指令是反向/全类清理（'杀掉所有 chrome 除了我在用的'）：必须先全类枚举建立白名单，收窄首扫不适用
- 点名属性可能属于正在运行的活跃会话（同名 e2e-profile 目录被当前测试占用）：仅子串匹配不足，需 PPID/启动时间/锁文件等强证据，否则停手
- busybox/嵌入式 ps 不支持 -eo 关键字：command 同样失败，应读 /proc 或用平台原生命令
