---
method_id: defer-shared-store-schema-migration-until-old-writer-exit-d438adc4236f
name: defer-shared-store-schema-migration-until-old-writer-exit
description: 在两阶段发布窗口内（重启回执如 waiting_for_requester_exit 表明旧进程未退出）给持久化 store 迁移新 schema 字段时，先确认旧版本写者是否已释放该 store：旧进程存活、其序列化器不认识新字段，下一次重写就会把新字段抹掉。应把迁移绑定到旧 pid 退出之后执行，并把『迁移完成』的报告门在退出后新字段回读存活上，而不是先写盘再补救。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:833:7a3a5bef1f502276ac1f
evidence_refs: learning:learn:8ffe10870a2c
created_at: 2026-10-19T11:05:24.382376+08:00
updated_at: 2026-10-19T11:05:24.382376+08:00
---
## Trigger
任务要求在发布/重启尚未收敛的窗口内，向一个仍被旧版本进程持有并周期性重写的持久化状态文件（如 schedule/task store）添加新 schema 字段并迁移既有条目

## Discriminator
重启回执明确旧进程未退出（waiting_for_requester_exit）＋ store 数据含由运行中进程维护的活性字段（lease_owner/wake_owner_pid/retry 等持续更新的键，证明活写者在重写该文件）＋ 新字段仅存在于尚未上线的代码：三者同时成立即预告旧写者会按旧 schema 重写并丢弃未知字段

## Short path
- 迁移落盘前先读发布/重启状态回执，解决唯一先决未知量：此刻谁在写这个 store（旧 pid 是否已退出）
- 若旧写者存活且其代码不认识新字段：不立即写迁移，把迁移注册为旧 pid 退出事件的回调（后台守护或定时唤醒），而不是写完再观察
- 旧 pid 退出且新 generation 收敛后，一次性执行幂等迁移（参数如次数/有效期/工作目录在迁移时钉死）
- 迁移后连续多次回读 store，校验新字段存活且值正确，通过才判定『迁移完成』
- 异步收尾未核验前，向用户如实报告『待自检唤醒核验』而非宣布成功

## Stop conditions
- 旧 pid 已退出、新 generation 收敛，且迁移写入的新字段在退出后的连续回读中存活
- 或确认 store 只有一个写者且该写者已在运行包含新 schema 的代码

## Verification
- 迁移后直接回读状态文件或管理面板，确认新 schema 字段仍在且值正确
- 确认最后一次重写来自退出后的新进程（pid/generation 对得上），排除旧进程残留写的假阳性存活

## Counterexamples
- 旧进程已退出，或该 store 从不被旧代码路径重写（单写者）：可立即迁移，守护/延迟纯属多余
- 旧序列化器对未知字段前向兼容（原样透传 dict 而非按 dataclass 重建）：旧进程重写不会丢字段，直接迁移即可
- 新状态写入独立新文件或 append-only 日志而非共享 store：不存在旧写者抹字段问题，不适用本方法
