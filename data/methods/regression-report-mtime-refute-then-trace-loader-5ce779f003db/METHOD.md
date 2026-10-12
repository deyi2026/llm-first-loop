---
method_id: regression-report-mtime-refute-then-trace-loader-5ce779f003db
name: regression-report-mtime-refute-then-trace-loader
description: 当一份可能过时的报告声称磁盘上的配置 artifact 从新版本 B 回退到旧版本 A，并要求找出“是谁写回的”时，先读该 artifact 的 mtime 和 hash：mtime 早于 alleged B 事件时间点，就在物理上否定了任何写回，可以立即取消 writer 追查。然后转向 consumer 溯源：从存活消费者的入口（进程命令行或模块树）读它的配置加载优先级代码，找到真正的权威来源，并在那里验证“丢失”的状态。用两跳窄路径替代全库文件名 grep、跨目录 hash 扫描和审计日志翻查。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:518:5977d5d4f29031dabd78
evidence_refs: learning:learn:1356ffab64e0
created_at: 2026-09-19T22:51:32.524915+00:00
updated_at: 2026-09-19T22:51:32.524915+00:00
---
## Trigger
收到的报告（可能由另一个 agent 更早生成/转发）断言某个磁盘配置 artifact 从版本 B 回退到版本 A，要求先定位 writer/authority 再重新写入；且报告的其他前提（分支状态、merge 状态）本身可能已过时，需要先核当前事实。

## Discriminator
只需一条便宜命令即可观测的事实组合：artifact 的 mtime 早于 alleged B 版本事件的时间戳，且内容 hash 等于 A。二者同时成立即证明事件发生后从未发生过写入——不存在 writer，报告盯错了文件。此外，存活消费者的进程命令行直接指明其加载代码模块，该模块的 load/persist 优先级（如 env > 本地 override 文件 > tracked seed）定义了真正的权威来源。

## Short path
- 用便宜的当前事实重验报告前提（PR/status API、git HEAD、artifact hash），把报告当假设而非现状，避免重复合并/修复。
- 读被指“回退”的 artifact 的 mtime；若早于声称的 B 版本事件时间点，宣布“写回在物理上不可能发生”，取消 writer 追查。
- 经消费者入口（进程命令行或一次定向模块列表）定位其配置加载模块，读取加载/持久化优先级（例如 env > local override 文件 > tracked seed）。
- hash 并检查最高优先级真实来源中是否包含报告称已丢失的字段/值。
- 若存在，再做一次便宜检查确认存活消费者没有被更高优先级的 env 变量覆盖；据此从加载顺序直接回答“重启后是否保持”，停止。

## Stop conditions
- artifact mtime 早于 alleged 回退事件：不存在 writer，停止一切 writer 搜索，转为溯源。
- 按加载优先级确认的权威来源中已包含报告声称的目标状态：警报解除，判定为 false positive。
- 消费者确认绑定权威来源且无更高优先级 env 覆盖：重启持久化问题已由加载顺序回答，汇报并停止。

## Verification
- 权威 override 来源的 sha256 等于报告中“变更后”版本的 hash。
- 实际读到（而非假设）加载代码，确认被指回退的文件是 by-design 只读 seed 且优先级更低。
- 消费者进程环境变量中不存在优先级高于该 override 来源的配置项。

## Counterexamples
- mtime 晚于 alleged 回退时间（或文件经原子替换写入）：写回真实发生过，此时审计日志/file_effect 的 writer 追查才是正确路径，不要转向 loader。
- 系统没有 override 层、消费者只读单一 tracked 文件：字段是真的丢了，应通过正式 authority 重新写入，而不是宣告误报。
- artifact 由无本地可读加载代码的外部服务消费：无法做 loader 溯源，基于日志的追查仍然必要。
