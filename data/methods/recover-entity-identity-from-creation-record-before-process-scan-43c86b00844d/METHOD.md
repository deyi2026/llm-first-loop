---
method_id: recover-entity-identity-from-creation-record-before-process-scan-43c86b00844d
name: recover-entity-identity-from-creation-record-before-process-scan
description: 后台 job/句柄失联（orphaned、local_handle=false）时，失联回执只有状态字段、不含该 job 的命令行——此时用猜测关键词扫进程表只会空命中。先从权威创建记录（本 session 事件流 action_trace 里 spawn 该 job 的 execute_command 参数，或 job 持久状态）取回实体身份（可执行名/端口/路径等判别 token），再用精确 token 做一次窄查（ps | grep <token>，核对 PPID=1、etime 与提交时间吻合），并区分'句柄丢失的事故孤儿'与'nohup 有意分离的常驻'。反模式：盲猜关键词；grep 宽 token（serve/python 会命中系统 daemon）；在 macOS/BSD ps 上用 GNU-only 选项（--no-headers）。创建记录不可得或实体有已知唯一副作用（固定端口）时，宽枚举/直接探测才是合理起点。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d643a7c4-20a9-438d-a61f-dd25be27bf55:522:0daa23005719ca2bf896
evidence_refs: learning:learn:d0759d238b42
created_at: 2026-10-16T21:56:31.410989+08:00
updated_at: 2026-10-16T21:56:31.410989+08:00
---
## Trigger
后台任务/锁/会话等控制句柄失联（orphaned、handle=false、kill 已不可达），需核查底层实体（进程/文件/连接）是否仍存在，且回执本身不含实体标识（命令行/路径）时

## Discriminator
失联回执的字段本身：只有状态与 0 行输出、没有命令行——说明当前未知量是'该 job 当初执行了什么'；而该 job 由本 session 提交，session 事件流 action_trace 原样记录着 spawn 时的完整命令参数，是实体身份的权威来源。用无 provenance 的猜测关键词（如 krate/autorun）grep 进程表，空命中不提供任何信息。

## Short path
- 读 job 状态回执，确认 orphaned/句柄丢失；注意到回执无命令行 → 未知量锁定为'该 job 当初执行了什么命令'
- 查本 session 事件流（query=execute_command/run_in_background）取回 spawn 该 job 的原始命令行，提取判别 token（可执行名+端口/路径，不用 serve/python 这类宽词）
- ps -axo pid,ppid,pgid,stat,etime,command | grep <判别token>（BSD 兼容写法，不用 --no-headers）：核对 PPID=1（被 init 收养）且 etime≈job 年龄
- 对命中 PID 精确复核资源（ps -o pid,ppid,rss,etime -p ...），并把同项目相关进程分类：句柄丢失的事故孤儿 vs nohup 有意分离的合法常驻
- 输出存活判定+资源占用+处置选项后停止；不做全量 PPID=1 或宽关键词枚举

## Stop conditions
- 进程表命中进程的命令行与创建记录逐字一致（含端口/模型路径），且 PPID/etime 证明是同一实体
- 事件流查不到该 job 的创建记录（跨 session 提交/日志已轮转）→ 才切换到按时间窗+PPID=1 的宽枚举
- 实体已有可直接探测的唯一副作用（已知端口/锁文件）→ 直接探测即止，无需翻事件流

## Verification
- 命中进程 args 与事件流记录的原始命令逐字比对（尤其端口、模型路径）
- etime 与 job 提交时间戳吻合、PPID=1，排除同名巧合进程
- 明确标注哪些是本次失联事故孤儿、哪些是有意 nohup 常驻，避免误杀合法服务

## Counterexamples
- job 回执已直接包含命令行/PID → 无需查事件流，直接窄查进程表
- 创建记录不可得（别的 session 提交、日志已轮转）→ 时间窗+PPID=1 宽枚举才是正确起点，本方法不适用
- 用户已给出唯一可探测标识（如固定端口）→ lsof -i :port 或 curl 探测比翻事件流更快
- 判别 token 太通用（python、serve）→ 应改用多 token 精确匹配（路径+端口），而不是退回宽枚举
