---
method_id: verify-restart-policy-by-exit-class-coverage-08369e9ff0d4
name: verify-restart-policy-by-exit-class-coverage
description: 为常驻服务落地守护（systemd/容器/supervisor 的声明式重启策略）时，重启策略是对退出结局类别的谓词：on-failure 只覆盖非零退出与异常信号，'kill -9 能拉起'只验证了最容易的一类。先从策略取值反推它区分哪些退出类（异常信号/非零退出/干净 exit 0），对照目标态'始终在线'找出未覆盖类，补策略或显式接受留缝；验证时每类注入一个代表事件（kill -9 与真实优雅关闭路径各一），以新 PID+NRestarts+健康探针三证收口，避免等真实中断才返工。
aliases: on-failure 不重启 exit 0, 保活验证只 kill -9 不够, 优雅退出后服务没了没人拉起, systemd 干净退出不拉起算不算故障, 重启策略按退出码分类验证, 守护单元自愈测试怎么设计
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:2e452d37-c246-40c6-9df5-b263eefb9cbb:329:d958725149dc5dd95f71
evidence_refs: learning:learn:e26e7e879c6c
created_at: 2026-11-06T20:09:35.789655+08:00
updated_at: 2026-11-06T20:09:35.789655+08:00
---
## Trigger
给常驻服务配置或验证崩溃自愈/开机自启（systemd Restart=、容器 restart policy、supervisor autorestart 等声明式重启策略），准备宣布'守护已验证'时

## Discriminator
策略字段取值本身就声明了谓词边界：单元文件/容器配置里写着 Restart=on-failure（只重启失败类），而任务目标态是'服务始终在线'——两者在验证当时都已可见，据此即可推出'干净退出 exit 0 不会重启'这个未覆盖类，不需要等真实中断才发现

## Short path
- 写完单元后先读回重启策略取值，列出它区分的退出类：异常信号、非零退出、干净退出 exit 0
- 对照目标态'始终在线'找类覆盖差：on-failure 缺干净退出类 → 先改 Restart=always（或显式记录接受该留缝）再进入验证
- 对每个要求覆盖的类注入一个代表事件：kill -9 代表异常死亡；用真实优雅关闭路径（SIGTERM→应用自行 exit 0）代表干净退出，不得用 kill -9 代替
- 每类核对三证：旧 PID 消失、新 PID 出现且 NRestarts 递增、健康端点恢复 200
- 全部类通过即停，不再对已验证的类重复注入事件

## Stop conditions
- 目标态要求的每个退出类都已注入一次代表事件并通过新 PID+NRestarts+健康探针三证
- 策略与目标态的覆盖差已显式记录并被接受（如 oneshot/维护场景有意不覆盖干净退出）

## Verification
- 对每个注入类：systemctl status 的 NRestarts 递增、Main PID 更换、健康探针恢复 200 三者同时成立
- 干净退出类必须走真实优雅关闭路径（SIGTERM 后应用自退 exit 0），复现策略谓词真正要裁决的那个结局

## Counterexamples
- Type=oneshot/批量任务单元：干净退出就是成功，改 Restart=always 会无限重启
- 容器 entrypoint 依赖外层编排器重启策略：exit 0 是交给编排器的信号，内层 always 反而抢职责
- 运维维护性停止属有意的干净退出，不应因'停止后没拉起'判策略失效（显式 systemctl stop 本就不触发重启）
