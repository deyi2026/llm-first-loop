---
method_id: snippet-truncated-or-undecodable-read-full-record-via-tolerant-script-856397eaf4ac
name: snippet-truncated-or-undecodable-read-full-record-via-tolerant-script
description: 回执点名实体 ID 并要求核实状态后继续时，若检索已唯一命中但正文被截断、或 shell 直读数据文件报带字节位置的 UnicodeDecodeError，瓶颈在呈现层而非发现层：不要原样重发同一查询（零新增信息），也不要换 shell 文本工具重试（共用同一输出解码路径、必败）。改用一个小脚本以 errors='replace' 打开账本/store 文件、按回执 ID 过滤，一次打印完整命中记录（status+content），同时闭合『核实状态』与『取获批全文』两个未知量。与『按 ID 查登记簿』类卡互补：那张定查哪条，本卡定截断/坏字节时如何把整条读出来。
aliases: 搜到记录只有半截怎么拿全文, cat 数据文件乱码或报解码错, 文件里有非法字节怎么读, 核实状态顺便取提案全文, 读整条记录别只看摘要
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6c13edc8-42f8-4bc3-9245-e19a3c891178:1165:a4400e9a56b0770aa94c
evidence_refs: learning:learn:df2caf745581
created_at: 2026-11-04T11:37:02.557934+08:00
updated_at: 2026-11-04T11:37:02.557934+08:00
---
## Trigger
回执/工单点名实体 ID、要求核实状态后继续；目标记录存于 append-only 账本或数据文件；检索工具只回截断摘要（命中唯一但正文在词中截断），或 shell 直读在输出解码层报位置确定的 UnicodeDecodeError

## Discriminator
两条当时即可见的事实：① 检索回执『命中 1 条』且记录身份（id/ts）稳定、正文截到词中间（如 input_token_budg）→发现已完成、只是该通道投影受限，重发同查询不可能带来新信息；② 报错为带字节位置的 UnicodeDecodeError（非超时/权限/暂态）→文件字节本身非 UTF-8，任何原样 dump 的 shell 文本工具都走同一条解码路径、换工具重试必然同样失败

## Short path
- 从回执提取全部实体 ID 与记录类型，显式列出两个未知量：状态是否属实、获批全文范围是什么
- 一次列目录（或用已知审计/数据路径）定位对应账本文件
- 单个小脚本：errors='replace' 打开账本、按回执 ID 过滤、打印完整命中记录的 status 与 content 字段——两个未知量一次闭合
- 状态字段与回执一致→核实闭合，按全文 content 直接进入执行；仅当按 ID 未命中才扩大到事件流等宽通道交叉验证

## Stop conditions
- 命中记录的状态/override/时间戳与回执一致，且 content/actions/impact_scope 完整在手（无词中截断）
- 容错脚本成功读取一次后，不再对同一批文件做任何原样 dump 式重试

## Verification
- 脚本输出与回执逐字段对照（状态、human_override、ts）
- 打印的 content 延伸到记录末尾、无 mid-token 截断，evidence/actions 字段可完整解析
- 若此前发生过解码失败：确认新读取路径不再触发 UnicodeDecodeError

## Counterexamples
- 报错无字节位置、呈暂态特征（pipe 中断、超时）→先原样重试一次，再考虑写脚本
- store 提供原生按 ID 查询且返回全文→直接用查询通道，不落到文件层
- 检索工具本身已返回完整正文→比对后即收束，无需再访 store 文件
- 文件确认小且纯 UTF-8→cat/jq 一次即可，写脚本属过度工程
