---
method_id: derive-verification-probes-from-colocated-change-record-30a94c9bddc3
name: derive-verification-probes-from-colocated-change-record
description: 核实已产出 artifact 是否包含此前声称的修改集时，若同目录/同批次存在声称这些修改的权威记录（优化报告、changelog、manifest、PR 描述），先读记录取出每项修改的确切探针键（标识符/选择器/期望计数），再对 artifact 做一次性探测；不从记忆猜键名。省去『猜键→0命中→再查记录→重测』的来回，也避免据 0 命中误下『特性缺失』结论。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:59688c5b-5ae5-42ee-9d63-23685fb569d6:237:f52b0a513c5691d725b2
evidence_refs: learning:learn:c60104b4fd25
created_at: 2026-10-17T20:24:20.819329+08:00
updated_at: 2026-10-17T20:24:20.819329+08:00
---
## Trigger
需要验证一个已生成 artifact（SVG/代码/配置/文档）确实落实了此前声称的一组命名修改，且定位过程中已看见同目录存在按名字即声明『逐项列出修改及其位置』的变更记录文件

## Discriminator
进入验证前，目录列表已暴露该记录的存在（如 OPTIMIZATION-REPORT.md / CHANGELOG，且 mtime 与 artifact 同批）；记录的角色就是把每项修改映射到确切标识符与位置——这把『凭记忆猜 3 个键』缩成『从记录逐字取 N 个键』，记忆猜测的 0 命中本身不含任何关于 artifact 的信息

## Short path
- 声明路径 FileNotFoundError → 不猜文件丢失，按文件名从工作区根做一次定位搜索，得到真实路径
- 需验证 artifact 为最终版 → 先读同目录变更记录，逐项取出探针键与期望计数（标识符、颜色值、dur 时长等），不掺入记忆猜测
- 用记录原文键对 artifact 做一次性批量探测（grep/结构查询），命中计数与记录表格逐一对照
- 全部命中后，以消费方（面板/评审者）实际解析的路径基（工作区根相对）重新声明交付物，停止

## Stop conditions
- 记录列出的每个探针键都在 artifact 上命中，且计数/位置与记录一致
- 已用正确路径基重新声明，消费方可打开——不追加额外的『再确认几项』探测

## Verification
- 探针键必须逐字复制自记录文本；任何记忆补充的键单独标记，其 0 命中不得作为缺失证据
- 对照记录 mtime 与 artifact 生成时间，确认记录对应的是当前 artifact 版本而非过期版

## Counterexamples
- 同目录不存在任何变更记录 → 探针只能从生成器源码或用户验收描述推导，记忆+源码阅读是唯一途径
- 记录早于 artifact 最后一次重生成且生成器已改（mtime 可证）→ 记录键可能过期，应以生成器源码为准
- 声称修改是纯视觉/行为变化，无稳定文本标识（如『阴影更柔』）→ grep 探针不可用，需渲染相位对比验证
