---
method_id: record-status-field-before-ui-invisibility-forensics-8c035e25e0bc
name: record-status-field-before-ui-invisibility-forensics
description: 用户问“某条记录为何在 UI 列表/面板看不到”时，先用记录 ID 在系统真值存储（状态 jsonl/DB）中直接读取该记录的 status 与变更时间戳；这一条事实即可把假设空间（未写入/丢失/被状态过滤/读错数据区）缩到一两个。仅当 status 本应可见却仍不可见时，才去排查 serving 层（进程/端口/构建/多数据区）。UI 侧只需检查列表组件的默认过滤参数，不枚举整个 web 栈。索引检索（如 search_records）未命中≠记录不存在，应按字面文件名定位存储与读取方的路径解析（含 env override）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:19:dae187db9fb04eed2ccd
evidence_refs: learning:learn:b6cacd671222
created_at: 2026-09-18T13:31:56.113831+00:00
updated_at: 2026-09-18T13:31:56.113831+00:00
---
## Trigger
用户报告某具 ID 的记录在管理界面的列表/面板中不可见，且系统中存在可定位的持久化真值存储（如按行追加的状态文件）

## Discriminator
真值存储中该记录的 status 字段值及其变更时间戳（如 status=accepted、reviewed_at）：一条事实即可区分“数据丢失/未写入”与“仍在但被默认过滤器移出视图”

## Short path
- 按 ID 的索引检索未命中时，不要转宽泛内容枚举；改为按真值存储的字面文件名定向搜索代码中的读/写位置，得到存储路径与读取方的数据目录解析规则（含环境变量 override）
- 在解析出的存储文件中按 ID 定位记录，读出 status 与 reviewed_at/updated_at 时间戳
- 若 status 与 UI 默认展示状态不符：只检查 UI 列表组件的默认过滤（默认 tab/status 查询参数），即可解释“看不到”
- 在变更时间戳处用单一权威日志（访问日志或执行日志）钉死变更来源与操作者
- 向用户报告记录现所在视图与变更时间线；解释成立即停止，不继续枚举进程/端口/构建产物/其他会话事件

## Stop conditions
- 记录 status 与 UI 默认过滤的组合已解释不可见，且变更来源由一个权威日志记录确认
- 存储路径与 UI 读取端解析的数据目录一致（含 env override）已核实

## Verification
- 变更时间戳与日志中该 ID 的变更操作（如 review POST 或执行日志条目）精确对上
- 用 UI 实际请求的 endpoint 参数（status 过滤值）复核默认视图行为

## Counterexamples
- 记录 status 正是 UI 默认应展示的状态但仍不可见：此时必须查运行实例/端口/数据区分裂/前端构建版本，本方法不适用
- UI 的数据源不是该存储文件而是 DB 或缓存 API：应先追 UI 实际 fetch 的 endpoint，定位 jsonl 是弯路
- 问题是排序/分页/权限而非状态过滤：status 字段不构成判别事实
