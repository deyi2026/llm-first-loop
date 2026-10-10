---
method_id: resolve-artifact-via-in-context-named-store-path-before-tree-wide-scan-7bd072d0a325
name: resolve-artifact-via-in-context-named-store-path-before-tree-wide-scan
description: 定位残留配置/指针/产物时，先汇总本次会话已读文档中显式点名过的存储目录，对其实施精确 ls/read，而不是对整棵工作树做 find/grep。含追加式事件日志的仓库里，全树扫描会以命令超时（60s）告终且零产出；同一批文档通常也点名了应排除的巨型目录。仅当被点名目录未命中时，才做一次排除批量数据目录、限定 src/docs/scripts 的定向扫描；全树扫描超时后不得原样重试，必须降级为点名精确路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:965:d41c27d7bba8c65d1322
evidence_refs: learning:learn:7df553d44571
created_at: 2026-10-09T23:39:03.665946+08:00
updated_at: 2026-10-09T23:39:03.665946+08:00
---
## Trigger
需要定位某个残留配置、指针通道或历史产物（如“旧配置文件在哪、指针挂在哪个通道”），且本会话已读过的权威文档曾显式引用其存储目录路径；而下一步 tempted 动作是全树 find/grep。

## Discriminator
knowledge-at-time：在进入宽扫描之前，已读结果文档已明文写出目标所在的存储目录（data/ 下具体子目录及文件名模式），甚至点名了巨型日志目录（data/event_logs/*.jsonl）——即精确路径已在上下文中，全树枚举只会先撞上批量数据导致的超时，再回到同一个被点名目录。

## Short path
- 汇总本会话已读文档中出现过的存储目录/路径引用
- 对被点名目录做精确 ls/read，目标文件通常直接浮现
- 读取命中文件并核对其字段（schema/关键配置项/有效期时间戳）确认即目标
- 仅当被点名目录未命中时，才做一次排除批量数据目录、限定源码/文档范围的定向扫描；禁止含 data/ 的全树扫描

## Stop conditions
- 在已点名的存储目录中找到目标产物且内容字段核对一致
- 被点名目录不存在或为空：升级为一次排除批量目录的定向扫描，仍不命中才考虑其他发现手段

## Verification
- 命中文件路径确实位于已读文档所引用的目录之下
- 文件内容与所寻目标匹配（含预期的配置键与时间戳，而非同名异物的临时文件）

## Counterexamples
- 目标在上下文与任何已读文档中均无路径引用、也无明显存储目录：此时发现式扫描是正当第一步（但仍应排除批量数据目录）
- 搜索目标本身就是大日志的内容（日志取证场景）：目录排除规则不适用，应改用按时间/按 seq 的定点日志读取
- 文档中的路径已过期（工作区迁移或目录改名）：先 ls 验证目录存在，失败即回退到定向扫描，而不是迷信旧路径反复重试
