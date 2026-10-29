---
method_id: identifier-form-differential-before-credential-matrix-9e19f844cedd
name: identifier-form-differential-before-credential-matrix
description: 服务进程调上游报『模型/标识符不存在』，而你用同一凭据直接探测裸名成功时，剩余唯一未知量是『服务实际发出的字符串』。先 diff 失败回执归属行的全限定 model_ref（provider/model 带前缀）与你实测成功的裸名；再用运行进程自身的启动日志/runtime manifest 的 per-key source 映射确定哪个配置文件胜出（本例 runtime.toml 覆盖了 .env，且本机缺 provider 注册使兜底把整串前缀名当模型代码发出）；最后同凭据做一次裸名 vs 全限定名成对差分探测，一侧复现上游错误码即闭环。凭据已验证后不要再枚举 key×端点组合或全盘扫 .env。
aliases: curl通了但服务还是报模型不存在, 模型名带斜杠上游不认, 1211模型不存在怎么查, key没问题服务还是调不通模型, 配置被runtime.toml覆盖了怎么确认
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1787:5525df8b84ddae5f3f5e
evidence_refs: learning:learn:4eb58ccb38d6
created_at: 2026-10-29T21:03:13.074550+08:00
updated_at: 2026-10-29T21:03:13.074550+08:00
---
## Trigger
服务/桥接进程调用上游 API 报『模型不存在/identifier not found』类错误，而你用同一凭据与端点直接探测裸标识符成功；或失败回执的归属行里标识符呈 provider 前缀的全限定形式（含斜杠）。

## Discriminator
失败摘要归属行打印的 model_ref（带 provider 前缀的全限定形式）与第一次成功探测时上游回显的裸标识符不一致——该字符串差异在首次 curl 成功后即可见，足以把『key 错/端点错/注册错』的多维假设缩为『服务发出的字符串形式不同』，并进一步用进程 manifest 的 key→source 映射锁定胜出的配置文件。

## Short path
- 从失败回执归属行提取服务实际使用的完整 model_ref，确认是否带 provider 前缀/命名空间斜杠
- 用运行进程自身产物定权威配置：/proc/<pid>/fd 或启动日志里的 config_file 与 runtime manifest 的 per-key source 映射，确定该键由哪个文件供给（避免全盘扫 .env 候选）
- 读胜出的配置文件，拿到服务真正会发送的字符串
- 同凭据同端点做一次成对差分探测：裸名 vs 全限定名——一侧成功一侧复现上游错误码即闭环根因（前缀未被解析/注册缺失导致兜底直发整串）
- 走系统设计的本地通道修复（如注册缺失的 provider），重启后验证 manifest 中 provider 已切换、出站请求体 model 字段为裸名，停止

## Stop conditions
- 成对差分探测复现了与失败回执一致的上游错误码，且修复后进程解析产物（manifest/请求体）显示发送的是裸标识符
- 若裸名与全限定名在上游都失败，则标识符形式不是判别轴，转凭据/端点/模型下线方向

## Verification
- 修复后读进程 manifest/启动日志，确认 provider 从 default 变为目标 provider
- 确认出站请求体的 model 字段为裸标识符（代码级或日志级检查）
- 让上游对该服务的新调用成功，或差分探测中原失败侧在修复后转成功

## Counterexamples
- 自己的探测也失败（裸名同样报不存在）→ 是凭据/端点/模型真下线问题，字符串形式差分无意义
- 上游本来就以 namespace/model 全限定名为规范形式（某些网关）→ 裸名反而被拒，差分方向相反
- 失败回执不含归属行、无法得知服务发送的字符串 → 应先抓进程实际出站请求体，而不是猜配置文件
- 错误是配额/权限类（429/403）而非『不存在』→ 标识符形式不是判别轴
