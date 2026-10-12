---
method_id: re-anchor-environment-via-runtime-self-introspection-6ebf2f77b467
name: re-anchor-environment-via-runtime-self-introspection
description: 跨时间/跨环境续跑任务中，一旦基于记忆或上一环境的绝对路径收到第一条确定性结构失败（目录/文件不存在），立即停止对该路径类做变体枚举（去后缀、换父目录）或检索旧 trace 考古旧路径；改用当前运行时自身的机械自省（echo $HOME; pwd; ps）一步重锚真实环境根，之后只在锚点内做窄搜索。本集该判断本可省去 3-4 次低产动作（两次目录不存在、一次空主目录 ls、一次未命中的旧 trace 检索）。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a6632d9a-6571-4eae-8529-58b0ba64fbb3:124:8edfe16d6a315f678712
evidence_refs: learning:learn:f5793f3a5d23
created_at: 2026-09-28T07:43:43.076973+08:00
updated_at: 2026-09-28T07:43:43.076973+08:00
---
## Trigger
任务经人工审批/面板重启后续跑，需定位真实代码树或数据目录而手头只有上一环境的记忆路径；或刚收到一条『目录不存在』类确定性失败回执，且模型自己已产生『环境可能已迁移』假设。

## Discriminator
失败回执是结构性不存在（目录不存在/无此主机），而非暂时性（超时、权限等待）；本集第 4 步回执『目录不存在 <prior-environment-root>/learning』即属此类，且第 5 步模型已明说『昨晚用的路径与真实代码树不同』——漂移假设当时已在场。此时当前进程的 $HOME/pwd/进程表是必在、零成本、权威的环境锚点（本集 pwd 直接给出真实树 <repo-root>）。

## Short path
- 先验证任务状态：search_records 取 evolution 权威记录（顺带获得上次根因与技术线索），确认 accepted。
- 声明未知量『当前环境真实代码根在哪』，用一条命令自省：echo $HOME; pwd; ps aux | grep <关键词>。
- 在自省得到的树内窄搜索目标符号（grep runnable_jobs/TOML_SCHEMA）并交叉验证锚点（.env 目标键、journal 路径存在）。
- 锚点确认后进入任务本体（读代码、fold 事件流统计队列、实施修复），每步只解决一个未知量，不再触碰旧路径。

## Stop conditions
- 自省产出唯一环境根，且树内出现目标符号/数据的第一条命中——环境发现即止，转入任务本身。
- 仅当自省歧义（多个候选树/worktree/多机）时才扩大发现（进程 cwd、PYTHONPATH、worktree 清单）。

## Verification
- 锚点与后续证据交叉一致：pwd 指向的树内确实存在 journal 路径、.env 目标键、可 grep 到目标符号。
- 重放检查：从起点第一步自省即应产出与全部后续路径操作一致的根目录，且不再出现同类『不存在』回执。

## Counterexamples
- 失败是暂时性/权限类（挂载抖动、超时、等待授权）——判别点不同：回执非结构性不存在，重试或换权限路径合理，不应否定整个路径类。
- 任务目标本身就是恢复/迁移旧环境数据（如备份回滚）——检索旧记录、枚举旧路径是任务内容而非绕路。
- 会话未跨环境、记忆路径刚被验证有效——记忆路径仍是最佳先验，可直接使用；但第二次同类失败后仍应转自省。
- 自省存在多个候选环境根（多 worktree/多部署线）——『唯一锚点』前提不成立，此时才需要更宽的环境发现流程。
