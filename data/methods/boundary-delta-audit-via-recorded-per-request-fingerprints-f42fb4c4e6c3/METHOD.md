---
method_id: boundary-delta-audit-via-recorded-per-request-fingerprints-f42fb4c4e6c3
name: boundary-delta-audit-via-recorded-per-request-fingerprints
description: 当问题形如『某组件（工具清单/固定前缀/注入配置）跨重启或发版是否变了、是否存在、是否被注入』时，不要继续从组装代码推断实际行为；先探测系统自身是否已按次记录该组件的指纹字段（request.meta 的 tools_count、routing_registry_fp、stable_prefix_sha256、告警计数），再跨事件边界逐条比对。代码与配置阅读只用于确认『组件存在』与『记录器存在』；行为差异问题一律以已记录的指纹序列为准。仅当无记录器、或记录器本身是被质疑方时，才退回插桩或独立采集/实验。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8bc1cbb3-5fe5-44cb-9818-3acb329d2acb:435:f74beca87cc78a64e0dd
evidence_refs: learning:learn:2bd4635f23ee
created_at: 2026-10-11T18:10:07.691918+08:00
updated_at: 2026-10-11T18:10:07.691918+08:00
---
## Trigger
用户或循环对运行系统提出 delta 审计问题（『X 在边界 B（重启/发版/配置切换）前后是否改变/是否存在/是否注入』），且该系统带按请求持久化的遥测/事件日志。

## Discriminator
转向事件日志之前、输出中已出现的事实表明未知量早有权威记录：源码展示按 round 持久化的诊断（last_prefix_diagnostics/stable_prefix_sha256、session_store.record_transport_event），且 alert 计数查询已返回 0；随后 keys 探测确认 request.meta 含 tools_count/routing_registry_fp/provider_structure_fp。即：被质疑行为已有按次指纹，可比对，无需从代码推断实际发送内容。

## Short path
- 把被质疑点拆成逐条可判真的未知量：①实际发出的 tools 清单跨重启是否变；②固定前缀是否存在/是否被改；③经验注入作用域与库存是否有对症记录。
- 对①先确认记录器存在：早期源码已显示 record_transport_event/前缀诊断按 round 持久化，据此探测会话事件日志 request.meta keys，解决『有没有可比对记录』。
- 跨重启边界拉取逐次 tools_count + routing_registry_fp 序列比对：全部一致 ⇒ 『工具清单未变』闭环；旁证查告警计数（PREFIX ALERT FIRED?=0）。
- 对②读权威定义面：transport 的 preamble 常量确认前缀存在；git diff release..HEAD 对该文本为空确认本次未改。
- 对③grep 配置作用域开关（SEMANTIC_EXPERIENCE_ENABLED=0）+ 检索记录库确认存在对症 verified 经验 ⇒ 缺口定位为『作用域关闭』而非『无经验』。
- 每条未知量取得带时间戳/指纹值的权威事实后即停，不做确认性重复查询，也不继续读与 delta 无关的组装代码（如 fallback 链）。

## Stop conditions
- 每个被点名的未知量都已由记录/定义面/配置给出可引用事实（含时间戳与指纹值），无剩余未知量。
- 某未知量没有对应记录器且无法低成本插桩时，明确改道为插桩/单变量实验，而非继续源码考古。

## Verification
- 先做 schema 探测（列出记录 keys）确认字段语义后再写比对查询，不按猜测的字段名取数。
- 比对覆盖边界两侧全部样本（重启前各段与重启后全程），并附告警计数作旁证，而不是只抽两点。
- 结论以逐次记录值呈现（如 32 次 tools_count=74、registry_fp 一致），禁止『应该没变』式推断。

## Counterexamples
- 被质疑组件没有任何按次记录（如中间件不落 tools 指纹）⇒ 指纹法不可用，需先插桩或旁路抓包。
- 记录器本身是被质疑方（日志正由嫌疑中间件写入）⇒ 记录不权威，需独立采集后再比对。
- 问题是设计性/规范性的（『前缀该写什么』『经验该怎么注入』）⇒ 需读代码与设计面，指纹序列回答不了应然问题。
- 无明确事件边界或边界一侧样本缺失 ⇒ 无法差分，应转 root-cause 的单变量实验路径。
