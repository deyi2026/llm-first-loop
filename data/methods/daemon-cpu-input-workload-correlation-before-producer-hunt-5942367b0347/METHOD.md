---
method_id: daemon-cpu-input-workload-correlation-before-producer-hunt-5942367b0347
name: daemon-cpu-input-workload-correlation-before-producer-hunt
description: 当常驻系统 daemon/服务长期满载 CPU 且原因未知时，先做一次廉价的『输入-负载相关性』检验（采样它的物理输入：磁盘 I/O、网络包速率、队列速率），再决定要不要枚举候选生产者。输入≈0 而 CPU 满载 ⇒ 排除外部事件风暴假设，转向 daemon 自身持久状态：用免 root 可得的元数据（状态目录 nlink/size、uptime、RSS）确认病态膨胀，给出分级修复（温和重启进程 → 特权/恢复环境清理状态存储）。只有输入确实沉重时，top/lsof/逐个 ps 式的生产者枚举才是正确下一步。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f9aba285-2d5a-481b-822d-947b77dd9a79:0:999cbbce604e493e2b8c
evidence_refs: learning:learn:0281746723a7
created_at: 2026-10-11T23:24:39.011650+08:00
updated_at: 2026-10-11T23:24:39.011650+08:00
---
## Trigger
某常驻系统 daemon/服务持续（小时~天级）满载 CPU，原因未知；候选假设空间为『外部客户端/生产者在制造事件或请求风暴』与『daemon 自身持久状态膨胀/损坏导致自转』。用户通常已提供 sample/profile 类证据。

## Discriminator
一条约 3 秒、免 sudo 的输入负载采样即可二分假设空间：iostat/nettop 连续多次采样显示 tps/MB/s≈0（或包速率≈0），同时目标进程满载 ⇒ 不存在真实外部工作负载，进程在自身状态上空转；辅以免 root 可读的状态目录元数据饱和（本例 `ls -ld` 显示 .fseventsd nlink=65535，即 uint16 上限，约 65533 个子目录）证实状态病态膨胀。本例中该检验在第 8 次调用才执行，此前 4 轮（top 全表、空 lsof、逐个 ps、sudo 探测、log show、1 次超时）都在枚举生产者。

## Short path
- 从用户提供的 profile 确认目标进程、RSS、热点类型（字符串匹配/锁争用提示内部状态操作）；未知量：外部事件风暴 vs 自身状态自转。
- 第 2 步即运行一次输入负载采样（iostat -d 3 4 / nettop，免 sudo）；未知量：CPU 满载是否对应真实物理输入。
- 输入≈0 ⇒ 否证外部风暴假设；转查 daemon 持久状态存储：`ls -ld` 状态目录读 nlink/size 是否饱和（通常无需 root）。未知量：状态是否病态膨胀。
- 一次 `sudo -n true` 探测权限边界，据此设计修复分级；不再继续枚举生产者。
- 交付证据链（空闲 I/O + 满载 CPU + 状态目录 nlink 饱和 + 长 uptime/RSS/profile 热点）⇒ 诊断结论与分级修复（温和重启 → 特权清理状态存储），声明副作用，停止等待用户执行需特权的动作。

## Stop conditions
- 输入-负载相关性检验已给出二分结果：真实负载 ⇒ 换生产者枚举路径；输入≈0 ⇒ 内部状态病理
- 状态存储膨胀/饱和信号已从免 root 元数据（nlink/size）取到手，或已确认不可得并降级表述
- 诊断与分级修复已交付，剩余动作（sudo/重启/恢复模式）只能由用户执行

## Verification
- 结论中每个关键断言都能指回一条已执行命令的可审计输出（本例：iostat 四次采样 0 tps；ls -ld nlink=65535；log show 5 分钟仅 28 行；sample 热点 strncmp/mutex；ps 42 天 uptime、3.1G RSS）
- 区分了『相关进程 CPU 也高』与『制造了真实文件系统事件』——用 iostat 否证而非默认因果关联（pytest/feishu 进程有 CPU 占用但不解释 fseventsd）
- 修复建议附带验证方式与副作用声明（重启后日志回放期 CPU 高属正常，5 分钟后复查；清理状态存储会触发 Spotlight/同步类客户端全量重扫）

## Counterexamples
- iostat 显示持续高 tps/MB/s 与 CPU 同步 ⇒ 真实事件风暴存在，此时生产者枚举是正确下一步，本方法应立即让位
- CPU 密集但输入天然与 I/O 弱相关的 daemon（本地索引、压缩、编译/计算服务）：I/O≈0 不能推断内部病理，需先确认该 daemon 的输入信号是什么
- 状态存储路径需 root 才能 stat 或 nlink/size 不可读：膨胀信号取不到时不得套用本方法强行定罪，改用 uptime/RSS/profile 旁证并降级结论
- 刚开机或刚清理后几分钟：日志回放期 CPU 高是正常行为，不构成病理证据
