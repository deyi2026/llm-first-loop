---
method_id: index-hit-truncated-follow-store-backing-file-not-workspace-sweep-0f2d10b2ba36
name: index-hit-truncated-follow-store-backing-file-not-workspace-sweep
description: 记录检索工具已按 ID/关键词命中目标记录、但回执正文被展示层截断时，命中本身就是 provenance：全文确定存在于该检索背后的 record store，截断不等于内容缺失。此时不要用同一标识符重扫全工作区、也不要枚举 data 目录，而是把唯一未知量收窄为『该 store 的物理落盘路径』——它通常已被 repo 内以子系统命名的自述文档（experience 卡/设计文档，文件名含 store 名与 data-dir）声明。读文档拿到路径后按 ID 做 keyed 读取；未命中再查 data_dir 主区/镜像锚定分裂。本集经全库内容扫描、根目录与 data 目录枚举、60s 超时命令等多次扩散探测才走到的位置，可缩为『读卡→grep JSONL』两步。
aliases: 搜索命中但正文截断去哪取全文, record store 落盘文件在哪, evolution 建议完整正文怎么读, 按经验卡定位记录存储路径, 索引截断别全库重搜
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:376f20bb-9dc9-4200-8780-a7b8dfab31db:64:2a2d47a75d225ff46df6
evidence_refs: learning:learn:cbea42f7d6f5
created_at: 2026-11-08T22:58:14.150913+08:00
updated_at: 2026-11-08T22:58:14.150913+08:00
---
## Trigger
search_records 类检索已命中目标记录（状态/正文部分可见），但正文被截断且任务继续需要完整记录内容；随后的取全文动作尚未发生或刚开始转向全工作区搜索/目录枚举。

## Discriminator
命中回执本身证明全文在检索覆盖的 record store 里（截断是展示限制）；据此排除『全文散落在工作区其他文件』的假设。唯一未知量=该 store 落盘在哪，而答案通常在 repo 自述文档中：以记录子系统名（前缀/工具名）命名的 experience/设计卡会给出 store 文件路径，且该文件名往往已出现在最初的目录列表或文档索引输出里——先沿这条边走，而不是先做宽枚举。

## Short path
- 按回执 ID 做一次登记簿状态查询，闭合外部状态变更核实（如 executing），不先拉宽通道
- 发现正文截断 → 不用同一 ID 重扫工作区、不枚举 data 目录；以记录子系统名（前缀/工具名）检索声明该 store 布局的自述文档（experience/设计卡）
- 文档给出 store 文件路径（如 <data_dir>/audit/<kind>s.jsonl）→ 对该文件按 ID 做 keyed 读取/grep，取全文
- keyed 读取未命中 → 检查 data_dir 主区/镜像锚定分裂（卡内常见教训），换锚定区重读一次
- 全文记录的 id/状态/审批时间戳字段与登记簿回执一致 → 停止发现，进入执行/实现

## Stop conditions
- 已按 ID 从 backing store 取到完整记录，且关键字段与先前登记簿查询逐字一致
- 检索面本身提供按 ID 取全文/详情接口并已取到 → 直接停，不追物理文件

## Verification
- 全文记录的 id、status、审批时间戳等字段与按 ID 的登记簿查询结果一致
- 确认所读文件属于记录所属进程当前实际锚定的 data_dir（防 split-brain 读错区）
- 截断恢复后内容与检索摘要的前缀逐字衔接（证明是同一条记录的完整版）

## Counterexamples
- 检索工具自带按 ID 取全文/详情视图 → 直接调用即可，物理文件追查是多余绕行
- store 为远程服务或数据库后端、无文件布局 → 应走 store 自有 API，文件路径思路失效
- 截断发生在写入侧（存储的本来就只有截断版）→ backing store 里也没有更多内容，须回到生产者补录
- 文档声明的路径已随 schema 迁移改名而读不到 → 降级为读 store 源码/设计文档推导命名方案（exact-path-only-discovery 方法的领域）
