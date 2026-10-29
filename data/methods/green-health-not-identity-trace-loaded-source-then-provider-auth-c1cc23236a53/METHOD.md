---
method_id: green-health-not-identity-trace-loaded-source-then-provider-auth-c1cc23236a53
name: green-health-not-identity-trace-loaded-source-then-provider-auth
description: 服务健康全绿（connected、心跳新鲜、零重连）只证明『某份有效凭证在用』，不证明『连的是用户要的那个主体』——旧而有效的凭证同样产出绿色指标。当用户钉死确切 app id/账号值时：先 diff 所有含该键的配置源；再用运行进程自己的 launch 日志 provenance 行（config_file=…）确定它实际加载哪份，不要读 loader 源码推加载顺序。修正时整组同步 key+secret（凭证成对才有效）、备份、重启。重启后 state 未恢复时，用确切键值对调一次提供方 auth 端点仲裁『凭证坏 vs 慢连接』：code=0 就有界等待，非 0 才回头挖配置链。收口=提供方验证通过+实时观测 connected+加载源内容与用户值一致。
aliases: connected但连错app怎么排查, 两个env文件APP_ID不一致信哪个, 心跳健康但身份不对, 改完凭证重启还是disconnected要等吗, 用auth接口验证凭证对不对
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1761:5000e1392e1ce4bca057
evidence_refs: learning:learn:2c3b33a3e063
created_at: 2026-10-29T20:56:39.202736+08:00
updated_at: 2026-10-29T20:56:39.202736+08:00
---
## Trigger
用户钉死一个确切身份值（app id / 账号 / 密钥指纹），而对应常驻服务健康指标全绿（connected、心跳新鲜、零重连），暗示它连到了错误主体；或身份修正+重启后 state 短暂未恢复

## Discriminator
凭证『有效』与『连对主体』是正交事实：旧而有效的凭证照样产出全绿健康指标。两个一次性判别事实：(a) 运行进程自己启动日志的 provenance 行（config_file=…、config_hash=…）直接指明实际加载的配置源；(b) 用进程应加载的确切键值对调提供方 auth 端点的返回码。心跳 state 永远回答不了『以谁的身份在连』。

## Short path
- 把用户钉死的值与所有含该键的盘上配置源做 diff，候选源收敛到1~2个
- 读运行进程自身的 launch/启动日志 provenance 行（config_file=）确定实际加载源；不读 loader 源码推加载顺序
- 加载源与用户值不符 → 只改加载源：整组同步 key+secret（凭证成对才有效）、备份原文件、重启进程
- 重启后 state≠connected 且进程存活 → 用确切键值对调一次提供方 auth 端点：成功=慢连接，有界等待后复查实时观测；失败=真配置问题，才回去定点查加载链
- 收口：提供方验证成功 + 心跳 ts 持续更新且 state=connected + 加载源文件内容=用户钉死值；转用户侧端到端确认

## Stop conditions
- 提供方 auth 对目标键值对返回成功，且实时观测恢复 connected，且加载源内容与用户钉死值一致——停止排查，转用户侧端到端验证
- 提供方 auth 失败且错误码明确指向凭证/参数无效——停止等待，回到配置链定点排查

## Verification
- 提供方 auth 端点返回码（如获取 tenant_access_token 返回 code=0，密钥全程不回显）
- launch 日志 config_file 行与当前进程 pid/启动时间对应
- 实时观测：心跳文件 ts 持续更新、state=connected、重连/断开计数为零
- 用户给 bot/服务发一条消息收到回复（最终端到端）

## Counterexamples
- 只有一个配置源且值唯一：不存在『加载了另一份』的假设空间，跳过 provenance 追踪，直接验证凭证有效性
- 服务进程已死或崩溃循环：健康全绿的前提不成立，先解决 liveness，身份排查放后
- 提供方 auth 端点受 IP 白名单/二次验证限制：一次调用失败不等于凭证错，改用身份可见旁证（提供方控制台的连接应用记录、bot 端到端回复）
- 重启后数秒内就查 state：长连接建立可有分钟级延迟，不等有界窗口就判定『配置回归』会误判（本例心跳冻结约90秒后自行 connected）
