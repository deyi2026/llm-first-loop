---
method_id: registry-first-service-restart-2d87ee392004
name: registry-first-service-restart
description: 仅适用于实际由 launchd/systemd/supervisor 等 OS 单元管理的服务：注册表的 unit label/域是重启句柄，不要猜 PID。LFL Web、Feishu、Learning 属于内建 managed service_control，必须使用其正式 action/lease/回执，不能用 launchctl kickstart 或 kill 绕过受管重启。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d90eb535-04f6-4fbd-a4da-6eac9c0eeabb:0:e6aaceee00ecb5007a94
evidence_refs: learning:learn:1f97f996cf55
created_at: 2026-09-19T12:28:39.332411+00:00
updated_at: 2026-10-26T06:56:06+08:00
---
## Trigger
用户要重启/查看某个服务，且已查明**该服务确实由 OS 级 launchd/systemd/supervisor 单元管理**、该单元属于正确用户域，并取得 unit label、live PID 与相应权限。此方法不用于 LFL 内建受管三服务。

## Discriminator
先识别**谁是权威控制面**：若服务由 LFL `service_control` 管理，则以其 desired/live/stable、维护锁和 action 终态为准，立即转用对应受管方法。若是独立 OS unit，确认 launchctl/systemctl 的域、label 和 PID；一个操作域的注册表不能推断另一个域或 root helper 的授权。

## Short path
- 只对确证的 OS unit：按平台读取单位注册表（例如 `launchctl list` 或 `systemctl status`），用厂商 label 定位，区分用户域与 system 域，不以模糊进程名替代。
- 确认许可、当前会话依赖及目标范围；权限不足就停止，不进行重复 sudo 或扩大重启目标。
- 对获授权的 OS unit 使用其官方 unit 重启命令，随后校验新 PID、unit 状态和实际服务入口，不盲扫额外进程。
- **LFL Web/Feishu/Learning 例外**：仅 `service_control` 正式 `publish`/`restart` + action_id 检查，先保证相同 Git 公共目录、配置有效、WebUI dist 绑定正确，遵守 worker lease、活跃任务锁、回滚；禁止 `launchctl kickstart -k` 或 `kill PID` 替代。

## Stop conditions
- 注册表无匹配单元、也未发现未注册的裸进程 → 停下来询问用户或进入有意的扩大发现，而不是反复换 grep 关键词。
- 目标单元属 system 域且 sudo 不可用 → 披露后停止，不做循环提权尝试。
- 重启后核实确认每个被 kick 的 label 都有新 PID 在跑 → 任务完成，不再追加扫描。

## Verification
- launchctl list 中每个被 kick 的 label 出现新 PID（Status 列 -15 是 kickstart -k 的预期 SIGTERM 痕迹，不是失败）。
- ps 确认每个新 PID 以预期用户、预期二进制路径运行。
- 已发现但未重启的单元（root 域 helper/service）在答复中显式披露，而非静默跳过。

## Counterexamples
- **LFL 受管服务 Web/Feishu/Learning**：权威接口是 managed `service_control`，不适用本方法“OS 注册表即重启句柄”结论。
- 目标是未注册裸进程，注册表无匹配：先看其原始启动方式，不能凭空制造 unit。
- 只有 system 域单元且无 sudo：不得尝试跨域或循环提权。
- 服务是当前交互连接依赖：知道 OS 句柄不等于得到“现在可安全重启”的授权。
- 在多个 user/system 域有同名单位时，不可仅凭模糊 alias 批量重启。
