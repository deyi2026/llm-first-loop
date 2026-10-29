---
method_id: sync-full-keyset-before-restart-under-config-file-drift-004c5955fa0c
name: sync-full-keyset-before-restart-under-config-file-drift
description: 多服务共用一份 env 配置文件、其中健康进程依赖的凭据键已不在当前文件中时，只补报错服务点名的那一个键就 kill 全部进程，会让原本健康的服务在重启后倒退回残缺配置（本 episode：飞书桥被杀后因 FEISHU_APP_ID/SECRET 不在 .env 而未启用，被迫二次挖备份+二次同步+二次重启）。规则：杀任何健康进程前先做键集 diff——健康服务实际在用的凭据/开关键 vs 磁盘文件键清单；有缺口就从同源备份一次性整组恢复（先比对非敏感锚键确认同源，密钥全程不回显），再一次性重启并按端点指标验证。
aliases: 重启前先核对env键完整性, 健康服务别急着杀 配置可能被改过, env被覆盖后重启丢凭据, 只补报错的key就重启会炸另一个服务, 老进程还活着说明配置被改薄了, 同源备份整组同步环境变量
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1481:c0efc779a4f9a95d3a99
evidence_refs: learning:learn:3272cb191c0a
created_at: 2026-10-29T19:42:36.548666+08:00
updated_at: 2026-10-29T19:42:36.548666+08:00
---
## Trigger
同一配置文件驱动多个服务：一个服务报『缺少必填环境变量』，另一个服务健康运行；且健康服务依赖的凭据/开关类键在当前文件键清单中完全缺失（文件在进程启动后被改薄的迹象）。

## Discriminator
kill 前已可见：健康进程的 heartbeat/日志证明其正在使用某类凭据（如飞书桥 state=connected、last_message_ts 新鲜），而其声明的 config_file 键清单里没有任何该类键 → 配置在进程启动后被重写，重启必然让健康服务回退；正确动作是整组恢复键集，而不是只修报错键就重启。

## Short path
- 进程/端口 triage：确定各服务运行与监听状态（未知量：谁失败、谁健康）。
- 读失败服务启动日志尾部，取显式缺失变量名（未知量：报错服务缺什么）。
- 只列配置文件键名+是否有值，与健康服务实际所需键集做 diff（未知量：文件是否已薄于进程启动时状态、kill 是否会毁掉只存在于运行进程里的状态）。
- 发现缺口 → 从同源备份整组恢复全部服务所需键：先比对非敏感锚键（如 LLM_BASE_URL 两端一致）确认同源，密钥用管道同步、只回显键名不回显值。
- 一次性重启全部被杀服务；端点验证：监听端口、代表性业务 API 200、常驻桥 heartbeat connected、密钥 1-token 最小连通性测试 200。

## Stop conditions
- 全部服务健康指标（端口/业务 API/心跳 connected）与密钥连通性测试均通过
- 发现配置实际由 systemd/声明式渲染管道权威生成时，停止备份同步路线，改查上游渲染源

## Verification
- 重启后日志不再出现第二次『未启用/缺少必填变量』类报错（出现即说明键集 diff 不完整）
- web 类服务：监听端口存在且面板/业务 API 返回 200
- 桥/常驻服务：heartbeat 达到 connected 并保持
- 密钥有效性：最小 token 请求返回 200；全程不打印明文值

## Counterexamples
- 报错源于网络/上游故障而非缺配置：键集 diff 无信息量，直接排查连通性即可
- 单服务且文件键集完整覆盖所需：常规修复+重启，不必挖备份
- 备份属不同 provider（非敏感锚键不一致）：整组同步会把端点/模型写错，须逐键核对或向用户索取新值
- 配置由托管系统渲染（systemd EnvironmentFile 生成、部署管道注入）：磁盘文件薄不等于漂移，应查渲染源
