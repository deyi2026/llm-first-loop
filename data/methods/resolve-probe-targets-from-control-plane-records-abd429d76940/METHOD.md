---
method_id: resolve-probe-targets-from-control-plane-records-abd429d76940
name: resolve-probe-targets-from-control-plane-records
description: 验证服务/重启结果时，先从系统自身控制面记录（动作回执的 detail、runtime manifest、控制脚本头部注释）解析出真实探测参数——端口、就绪端点、状态文件路径——再发起探测。对猜测地址的失败（连接 000、FileNotFoundError）只证明'地址猜错'，不构成服务异常证据。回执 detail 中命名的执行脚本就是现成 provenance 边。此法把'哪个端口/哪个文件/服务是否挂了'多个未知量缩成'读一份权威记录'单一未知量，避免全端口、全目录枚举式排查。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:010fcc8e-3ba8-4948-9ae5-66a30cc8ea6e:642:be7121ee5cdb09fdd9f2
evidence_refs: learning:learn:a57c9dbab168
created_at: 2026-09-17T15:06:53.897182+00:00
updated_at: 2026-09-17T15:06:53.897182+00:00
---
## Trigger
需要验证服务/重启/部署动作后的运行时状态，准备用 curl/lsof/读状态文件探测，但探测目标（端口、就绪端点、状态文件路径）尚未从该系统自身记录中确认时——典型场景：动作终态回执已到手，同时并行发起运行时探测。

## Discriminator
回执/工件中是否已有指向权威配置的 provenance 边：action 的 detail 字段命名了执行脚本（如 'restart_mirror rc=0'），且工作区存在 runtime_manifest* / 控制脚本，其头部注明真实端口与就绪端点。若存在，先读它们取得探测参数；猜测地址上的 000/FileNotFound 是关于猜测的信息，不是关于服务的信息。

## Short path
- 1. 取动作终态回执，确认 status/rc/generation（未知量：动作是否完成）。
- 2. 沿回执 detail 命名的执行脚本与 runtime manifest 读出权威探测参数：真实端口、就绪端点、状态文件路径（未知量：'正常运行'的判定标准由谁定义）。
- 3. 只探测这些权威目标：端口监听 + 就绪端点 + 心跳/manifest（未知量：运行时实际状态）。
- 4. 交叉校验 manifest 的 pid/started_at 与回执时间戳；不一致则枚举控制动作目录，确认是否存在更新的 superseding 动作（未知量：本动作是否已被后续会话覆盖）。
- 5. 若验证目标含'我的变更已生效'，对当前运行 worktree 的 git head 做 log/merge-base 血统核验。
- 6. 所有关键事实均由权威来源互相印证后停止。

## Stop conditions
- 回执 succeeded 且按权威端口/端点/心跳实测全部通过，运行 manifest 与最新动作记录一致（无未解释的更新动作）。
- 发现的 superseding 动作终态与运行时一致，且当前运行代码血统包含所需提交。

## Verification
- 探测的地址与返回码针对 manifest/脚本声明的端口与端点，而非假设值（如默认 8000）。
- manifest 记录的 pid 与 lsof/ps 实际监听 pid 一致；started_at 与最后一次成功动作时间的关系可解释（相同或被更新动作覆盖）。
- 当前运行 worktree 的 git head 经 log/merge-base 验证包含要确认的提交。

## Counterexamples
- 无控制面工件的第三方/未知服务排查：没有 manifest 或控制脚本可读，只能靠宽枚举（全端口扫描、ps 全表、目录发现）定位目标。
- 任务本身是端口盘点/残留进程审计（'该项目是否有进程蹲在任意端口上'）：全量 lsof 枚举就是方法本体，先读 manifest 反而漏检。
- 怀疑 manifest 已过时或服务 crash 后改绑端口（脚本头部记载的 Errno 48 撞端口类故障）：应以实际 pid 的监听事实为准，manifest 只作交叉项而非唯一真值。
