---
method_id: selective-strip-signature-concurrent-old-writer-on-shared-store-37369bc3984c
name: selective-strip-signature-concurrent-old-writer-on-shared-store
description: 新 schema 字段写入多进程共享的持久化 store 成功后、稍后重读即消失（或幂等迁移反复报『已应用/已有授权』而 store 中并无升级产物）时，第一未知量不是『迁移脚本哪里错』，而是『还有谁在重写这份文件』：用时间差快照的选择性剥离签名（整份文件秒级后被重写、仅新增字段被剥、旧字段保留）判定存在并发旧版本写者；盘点共享该 store 的进程并逐个核对其运行 commit 是否包含新 schema，先把旧写者对齐（重启/升级到新代码），再重放迁移/重建条目，最后用两次间隔重读（秒级+分钟级）验证持久性，而不是单次读回或循环重跑迁移。
status: active
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:1694:b4ee92b048a58cae3d8e
evidence_refs: learning:learn:ff1ba682cdd6
created_at: 2026-10-19T11:44:54.409940+08:00
updated_at: 2026-10-19T12:28:40.956980+08:00
---
## Trigger
多个长生命周期进程/守护服务共享同一份可变持久化 store（JSON/状态文件），且出现下列之一：① 新 schema 字段写入成功后，稍后重读发现字段消失或条目状态回退；② 幂等迁移重复报『already applied / already has grant』类错误，但 store 中查不到升级字段

## Discriminator
时间差快照对比显示：写入成功后数秒内文件被整份重写，且只剥掉本次新增的字段、旧字段与部分投影字段保留——这是旧版本序列化器覆盖的签名，可把候选空间从『写侧 bug / 迁移脚本错 / 环境问题』缩成『哪个进程在回写』；辅证是错误史表明该授权性写入至少成功过一次（否则是写侧失败而非状态回退）

## Short path
- 先消费已点名的失败工件：读迁移脚本与其日志尾部，拿到精确报错、store 路径、目标 id 列表，再做任何文件系统级枚举
- 直读共享 store，对照『成功写入应产生的字段』与『实际持久化字段』，确认这是状态回退而非写入失败
- 做时间差快照：触发一次写入→等数秒→重读，观察是否出现第二次整份重写及其选择性剥离，锁定第二写者存在
- 盘点写者：用 ps/lsof 找 cwd 或打开句柄含该 store 的所有进程；对每个进程取运行 commit 与启动时间，用 git show <运行提交>:<序列化文件> | grep -c <新字段> 验证旧代码是否缺失新 schema，并与其启动时间对比部署时间
- 先升级/重启旧写者到含新 schema 的代码，再重放迁移或重建条目——顺序不可反，否则新写入会再次被剥
- 间隔复查持久性（秒级与分钟级各一次），并确认所有共享进程的运行代码都含新字段后才停止

## Stop conditions
- 所有共享该 store 的进程均运行包含新 schema 的代码，且新字段在≥2 次间隔重读中完整保留
- 幂等迁移重跑返回『已升级/SKIP』且 store 中字段确实齐全，二者同时成立

## Verification
- 重跑迁移脚本应输出 SKIP/already standing 而非再次报错或再次写入
- 对每个共享进程核对运行 commit 是否包含引入新字段的提交（含启动时间 vs 部署时间）
- 写入后延迟两次重读（秒级+分钟级）确认无第二次剥离性重写

## Counterexamples
- 单进程独占的 store：字段消失应查自身序列化/写路径或写错文件，进程盘点无益
- 新字段从未写入成功过（写时即缺失）：是写侧校验/序列化 bug，时间差快照不会出现第二次重写事件
- 报『already applied』但字段完好：真幂等/调用顺序问题，直接跳过即可，无需排查第二写者
- 各服务使用相互独立的 store 文件：不存在跨写者剥离的可能
