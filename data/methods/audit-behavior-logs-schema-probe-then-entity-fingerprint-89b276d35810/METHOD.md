---
method_id: audit-behavior-logs-schema-probe-then-entity-fingerprint-89b276d35810
name: audit-behavior-logs-schema-probe-then-entity-fingerprint
description: 诊断某历史会话『重复探索/循环』的日志审计法：聚合脚本返回结构性不可能的零值（调用数为0但同批输出已有回执、文件MB级）时，先采样探明记录 schema 再重写聚合，不换措辞重试；重复用『工具+结果前缀』与实体标识（证据短哈希/命令前缀）指纹统计而非精确参数；按分钟分桶定位突变恢复段；最后交叉机制状态文件（压缩快照数、task_state 读/写比、gate_state 预算）把统计症状归到因果层（触发/放大/行为/熔断）。
aliases: 审计脚本统计出0次调用怎么办, 怎么统计同一证据被反复读了多少次, 日志里重复调用找源头, agent会话重复探索诊断, 压缩后恢复循环定位
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6c13edc8-42f8-4bc3-9245-e19a3c891178:1137:da561a5d66dfdd8211ec
evidence_refs: learning:learn:e37e8559e9b0
created_at: 2026-11-04T10:49:51.812548+08:00
updated_at: 2026-11-04T10:49:51.812548+08:00
---
## Trigger
用户报告某历史会话/agent 出现重复探索、循环或停滞并要求根因审计，且工作区持有该会话的结构化制品（archive jsonl、索引、audit、压缩快照、gate/task state 等）；或对这类日志做聚合统计时得到与文件规模/回执明显矛盾的零值或负结论。

## Discriminator
聚合结果与同批直接可见事实自相矛盾：如『工具调用总数: 0』而同一输出里已列出 N 条 stub 回执、归档近万行 MB 级——这证明记录 schema 与假设不符，而非行为不存在；同时，重复统计里冒出的『复用桩』回执本身就是去重机制的痕迹证据，不是噪音，应作为线索而非过滤掉。

## Short path
- 一次性盘点目标会话全部制品（archive/索引/audit/压缩快照/状态文件），确定审计面
- 先采样若干行并按 role 统计 key 元组分布，探明记录 schema（工具调用记在哪类行、params 是否持久化）；凡出现不可能零值，先修 schema 再重写聚合
- 在真 schema 上用（工具, 结果前缀）与实体标识（证据哈希/命令前缀）做重复分组，量化重复组数、多耗执行数、Top 重复实体及其首末时间跨度
- 按分钟分桶找突变段（如每分钟40次骤升到400+），该段即恢复/循环 regime，配合压缩快照时间戳对齐
- 交叉机制状态：task_state 读/写比、快照内嵌字符数、gate_state 预算口径，把统计症状归属到触发器/放大器/行为根因/无熔断分层
- 各层有量化指标+直读支撑文件后写经验卡/演进建议并交付结论，停止再统计

## Stop conditions
- 因果链每一层都有量化指标且指向一个直读的状态/配置文件，独立第二脚本复算计数不再变化
- schema 探查证明所需维度（如调用参数）未持久化——该项标注『日志不可判定』，不再换措辞重跑聚合

## Verification
- 用独立重写的第二脚本复核 Top 重复组与总计数，要求两版一致
- 抽查每个 Top 重复组的时间戳与实体标识，确认确为同一实体而非前缀/哈希碰撞
- 最终每条根因层都能回指一个直读制品（gate_state、快照 manifest、task_state 调用分布），而非纯统计推断

## Counterexamples
- 日志中已有明确报错栈/配置 diff 指向单一故障点——直接走因果链端点核查，无需行为聚合指纹
- 用户只想知道个别几次调用的语义内容——直读那几行即可，不要搭统计管线
- 日志仅几十行的小会话——人工通读比写 schema 探针脚本更快
