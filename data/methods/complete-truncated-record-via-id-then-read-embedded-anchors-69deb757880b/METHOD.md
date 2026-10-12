---
method_id: complete-truncated-record-via-id-then-read-embedded-anchors-69deb757880b
name: complete-truncated-record-via-id-then-read-embedded-anchors
description: 当权威记录（evolution/ticket/审批）的搜索命中唯一一条且内容明显截断，而回执已同时给出记录 ID/时间戳与内嵌代码锚点（file:line）时，不要对同一搜索类换措辞重查，内容 grep、『kind:ID』语法等变体大多 miss；改用按 ID 的事件流/记录通道一次取全量内容，并把代码定位从搜索问题变成直接读已引用的锚点区间。本集前 3 轮 4 次变体查询中 2 次 miss，event_stream 用原 ID 一次即取回全卡；记录内嵌的 CLI L3383-3465 / builtin L231-258 锚点事后全部命中，本无需重新定位。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:131:99fcc9565a030e8898f7
evidence_refs: learning:learn:1fe993827462
created_at: 2026-09-24T07:02:24.903375+00:00
updated_at: 2026-09-24T07:02:24.903375+00:00
---
## Trigger
需核实某权威记录状态时，search 类工具返回唯一命中但内容被截断（可见句中截断标记），且可见片段已含记录 ID、时间戳与具体 file:line 锚点；下一步动作开始对同一 source class 换参数重查（内容 grep、改写 query 语法、放宽 max_results）。

## Discriminator
回执三事实同时在场：(1) 单命中且带稳定 ID/时间戳；(2) 截断可观察（内容断在词中，说明全量存在于可按 ID 取的通道）；(3) 片段内嵌精确代码锚点（如『CLI L3383-3465 / 模型侧 builtin L231-258』）。这三点在首次命中时即已把『取全量内容』缩成一次按 ID 取、把『找代码位置』缩成读锚点，无需任何再搜索。

## Short path
- 记录唯一命中但截断：摘出 ID/时间戳/内嵌锚点；未知量=全量内容与权威状态。
- 用已在手 ID 走 event_stream/按 ID 记录通道一次取全卡，确认状态（如 executing）；不再发变体搜索。
- 一次文件名搜索把锚点中的角色（CLI/builtin）映射到真实路径，直接读引用的行区间，而非内容 grep 重找定义。
- 锚点内容与记录声称一致即停止发现，沿代码自身引用（如回执调用的 view 组合函数、导入块）补齐剩余数据源，进入编辑/测试/发布。

## Stop conditions
- 全卡已取回且状态与操作方回执一致；引用锚点区间已读且内容与记录描述吻合——立即停止发现层动作。
- 锚点行号与当前文件内容不符（代码漂移）时停止信任行号，改为按符号名定位一次。
- 按 ID 通道已成功取全后，不再对同一搜索类发任何变体查询。

## Verification
- 全量记录确实包含截断命中中缺失的字段（计划后半段/验收内容）。
- 所读行区间确为记录声称的那段回执/发布代码，而非同名其他区域。
- 对照最终实现位置：被修改的四个回执面与记录锚点所指的两侧（CLI/模型 builtin）一致。

## Counterexamples
- 命中内容完整、无截断标记：直接使用，勿再取事件流。
- 记录不含任何代码锚点：文件/内容发现层是必要的，本方法不适用。
- 记录陈旧、锚点行号与当前代码漂移（行区间内容对不上声称）：必须按符号重定位，不能沿用行号。
- 搜索 miss 是真负结果（记录根本不存在）：换通道取全无意义，应回到发现层或上报。
- 目标是并发写者的最新终态断言而非补全已知记录：属于先重读权威记录类方法，不是本方法。
