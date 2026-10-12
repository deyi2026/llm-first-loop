---
method_id: refine-in-serving-channel-before-storage-hunt-857ea050f5ae
name: refine-in-serving-channel-before-storage-hunt
description: 当某类 artifact 有专用查询通道（records/git 等），且你已持有精确标识符、该通道用此 ID 此前已 success 返回正文时，补足缺失细节应先在原通道内细化（更窄小节关键词、精确 ID、kind/limit 参数），而不是换层去文件系统找该 record 的物理存储文件，或在通道间插入全目录 ls/全库内容枚举。只有当原通道返回为空或报错，或其输出自己点名具体文件路径（沿点名路径属 provenance 边而非换层）时，才允许下沉。本集原通道按两个 EVO ID 均已精确命中提案正文后，'找存储文件读全文'的命令仍 60s 超时，属可避免的换层。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:495:39673435961fa33c5292
evidence_refs: learning:learn:cc84540054fc
created_at: 2026-10-12T06:54:37.370012+08:00
updated_at: 2026-10-12T06:54:37.370012+08:00
---
## Trigger
需要某已知记录/提案的更多细节（如设计档位、小节全文），且当时 (a) 手中已有精确 ID（审批回执/事件流点名的 record ID 或 commit hash），(b) 按该 ID 查询的专用工具此前已 success 并命中正文。此时出现的诱惑动作是'去找底层存储文件'或全库关键词搜索。

## Discriminator
同一通道+同一精确 ID 的上一次查询已 success 命中该 artifact 正文（本集 search_records(kind=evolution, query=EVO-…-65475c5a / EVO-…-bb3022f4) 均命中 1 条并返回提案正文），且 git log 已点名携带提案提交记录的 commit hash。这两条当时已知事实把'全文从哪获取'缩到'原通道内细化'一个选项，物理存储狩猎从一开始就无必要。

## Short path
- 盘点在手的精确标识符与已验证通道：EVO ID→records 通道，commit hash→git show（未知量：提案细节与改动面在哪）。
- 对每个未满足的细节在原通道内做一次精确细化查询：更窄的小节关键词（如 poll_wait 设计档位）或调 kind/limit 取全文（未知量：该小节内容）。
- 代码实施点走另一条点名边：git show 的改动文件/SRC 列表 → 读定义面 + grep 机制名 → 只读命中行段（未知量：机制落点），不在其间插入全目录 ls 或全库内容搜索。
- 所需事实交叉核对一致（executing 状态与回执一致、细节支持设计决策）即停止检索进入实施（未知量消失）。

## Stop conditions
- 所需细节已从与精确 ID/provenance 一致的来源取得，检索停止。
- 原通道一次细化后内容已足够支撑下一步动作。
- 原通道连续两次细化仍取不到目标内容 → 才允许换层，且换层动作须指向明确下一跳（通道点名的路径或 commit）。

## Verification
- 每条被引用内容可回溯到在手的精确 ID/commit，而非宽搜索的无关命中（本集 search_files 命中的 10 条全是 evals 指纹，属无效枚举）。
- 对同一未知量未出现换措辞重复查询或换层狩猎；无超时类失败动作（本集至少 1 次 60s 超时可省）。

## Counterexamples
- 专用通道只回元数据/指针、从未返回正文或直接报错——此时物理存储位置可能就是正当的下一跳。
- 通道输出自己写明'原文存于 <path>'——读该文件是沿点名 provenance 边，不是换层狩猎。
- 手中无任何精确 ID、只有主题——先按 kind+主题做定向发现是正常第一跳，本方法不适用。
- 要确认的是磁盘代码的真实行为而非记录内容——应直接读源码定义面（本集读 spawn_subagent.py 一次即确认 requires 仅启动前缺口校验、非排他），不要绕道记录系统。
