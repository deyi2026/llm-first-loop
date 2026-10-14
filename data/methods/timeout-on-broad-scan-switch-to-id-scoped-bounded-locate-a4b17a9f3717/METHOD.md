---
method_id: timeout-on-broad-scan-switch-to-id-scoped-bounded-locate-a4b17a9f3717
name: timeout-on-broad-scan-switch-to-id-scoped-bounded-locate
description: 记录库检索命中但正文被截断、需要全文与权威状态时，不要转向全目录内容扫描。若扫描类工具（search_files 或递归 grep/find）在超大目录上超时，超时回执本身即判别事实：本地 FS 全树扫描是确定性成本，换一个工具重扫同一棵树必然再次超时。改为有界结构定位：先 ls 数据根目录一层映射存储子目录，再用 find -maxdepth 2 -iname '*<记录类别>*' 钉住候选存储文件（如 audit/suggestions/exec 日志），然后用已知唯一记录 ID 直接 grep/解析，一次读取取得全文与 status 字段并与人工回执交叉核对。本集两次 60s 超时加 submissions 目录弯路，可缩为 2-3 步带界查找。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1897dc0c-c278-413c-b54d-22c50b97372f:1454:03d7c6d20e9dbcadc5d7
evidence_refs: learning:learn:0ef39f3d7ad5
created_at: 2026-10-14T12:19:14.286534+08:00
updated_at: 2026-10-14T12:19:14.286534+08:00
---
## Trigger
记录库（search_records 类）命中但回执正文被截断，仍需全文或权威当前状态；或扫描类工具（全树内容搜索/递归命令）在已知超大目录上返回超时回执（本地 FS 扫描成本，非网络瞬时错误）。

## Discriminator
超时回执明确指向本地扫描的确定性成本（同范围重试必然复现），且此前回执/用户输入中已存在唯一标识（记录 ID、记录类别名、store 命名模式），足以作为 name/substring 键做深度受限的结构定位，替代无界内容扫描。

## Short path
- search_records 命中但截断 → 待解未知量=全文+权威 status；不换词重查、不启动全树内容扫描
- 首个扫描超时回执到达后，停止一切同范围无界扫描；ls 数据根目录一层，映射 store 子目录（evolution/、audit/ 等）
- find <root> -maxdepth 2 -iname '*<记录类别>*' 钉住候选权威存储文件（如 suggestions/exec 日志 jsonl）
- 用唯一记录 ID 在候选文件内直接 grep/解析，一次取得全文与 status 字段
- status 与人工回执交叉一致 → 停止发现，进入执行

## Stop conditions
- 已从与记录类别/ID 匹配的权威存储文件取得全文与当前状态，且与回执声明一致
- 发现记录系统提供原生按 ID 取详情的工具/接口时，直接使用并停止文件定位

## Verification
- 解析所得 status 字段与人工回执声明的状态一致，记录 ID 完全匹配
- 确认所读文件属于该记录类别的权威存储（如 audit 执行/建议日志），而非缓存或过时副本

## Counterexamples
- 超时由网络挂载或瞬时 I/O 故障引起（非确定性成本）——一次有界诊断性重试合理，本方法的确定性前提不成立
- 记录系统本身提供 get-by-ID 详情接口——应直接调用，文件定位反而是弯路
- 目标内容没有唯一标识或特征文件名（自由文本、位置未知）——name 过滤无法收窄，需要限定子目录内的内容搜索
- 目录规模小、全树扫描秒级完成——分层定位纯属额外开销，直接扫即可
