---
method_id: recover-prior-session-state-via-command-provenance-not-keyword-search-5e12bd254b8d
name: recover-prior-session-state-via-command-provenance-not-keyword-search
description: 续轮任务需找回上一轮留下的接口细节/工件时，先按来源枚举上一轮的 provenance 记录（如 execute_command 回执）：其完整命令文本通常嵌有工作目录与工件文件名，可一步定位现场，再用 ls+cat 恢复确切的 endpoint/payload/token。避免在证据库反复猜关键词、或对与上轮无关的工作区做全量枚举；若 hydration 截断了命令文本，立即转向文件系统现场验证。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:180:6f6bda6efa3550b5af1f
evidence_refs: learning:learn:8f7ecc05db5a
created_at: 2026-09-18T02:18:37.476826+00:00
updated_at: 2026-09-18T02:18:37.476826+00:00
---
## Trigger
任务延续上一轮、需恢复上轮留下的状态/工件；按记忆猜的路径读取失败，且回执明确登记该路径此前就不存在（非瞬时错误），会话上下文显示上轮工作由命令行/工具调用完成。

## Discriminator
失败回执已登记该路径此前不存在（曾失败、TTL 内），同时上下文表明上轮是命令行/工具调用式工作——上轮真相的持久副本在命令记录及其写出的文件里，而不在当前工作区。这两个当时已知事实把『哪里都搜一遍』缩成『先读上轮命令记录，再查其工作目录』。

## Short path
- 接受『登记不存在』事实，放弃该路径；未知量：上轮状态存放在哪里？
- 按来源过滤/列出上一轮证据（source=execute_command，取最近记录）；未知量：上轮跑了什么命令、在哪里跑？
- hydrate 最近命令记录，从命令行文本提取 cwd 与文件名（命令常以 cd <dir> && … <file> 形式自带路径）；未知量：这些工件现在还在吗？
- 对揭示出的目录做 ls 枚举现场（请求/响应/token/报告）；未知量：成功请求的确切格式与已问过的问题？
- cat 成功请求与响应文件，恢复 endpoint、payload、鉴权细节，随即停止恢复、转入本轮新任务

## Stop conditions
- 已从磁盘现场读到与上轮证据一致的成功请求格式与所需细节（endpoint/payload/token），恢复即止
- 文件系统现场已被清理（目录为空/换环境），停止追路径，改为凭证据重建或向用户求证

## Verification
- 恢复的请求文件与上轮证据中的成功响应语义一致（同 endpoint/model/payload 结构）
- 工件时间戳与上轮证据 acquired_at 相符，确认是同一现场而非陈旧副本

## Counterexamples
- 上轮记录不含任何工件路径（纯内联结果、无文件写入），此时关键词条目检索或询问用户才是正解
- 文件只是路径拼错且确在工作区内：定向文件名搜索一步即可，无需走 provenance 链
- 运行环境已重置（如 /tmp 清空或换机），文件系统线索失效，应重建状态而非恢复
