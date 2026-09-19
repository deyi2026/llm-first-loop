---
method_id: exact-threshold-signal-goes-straight-to-construction-site-5a62fdd88773
name: exact-threshold-signal-goes-straight-to-construction-site
description: 执行缺陷修复类任务时，若权威记录（exec 记录/事件流/建议原文）已给出命名组件+精确量化故障边界+连接级失败签名，先做"阈值↔依赖库默认值"匹配（如 >1MiB 断连 ≈ websockets 默认 max_size=1MiB），再沿 registry→实现文件→传输层连接构造点做定向 grep/读码验证。跳过全仓内容搜索（会命中 eval 日志噪声）和重放上一会话的失败搜索路径，也跳过按文件名猜测路径的枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:550:6787405d1c639fc28ee8
evidence_refs: learning:learn:ac5936e2eeb7
created_at: 2026-09-18T03:56:37.869793+00:00
updated_at: 2026-09-18T03:56:37.869793+00:00
---
## Trigger
缺陷修复任务的权威证据中同时出现：(a) 具体组件/工具名，(b) 精确字节/数量阈值处的失败（如超过 1MiB 即断），(c) 连接级失败特征（connection closed / 1009 / 会话无法自救）。

## Discriminator
精确阈值与某个依赖库的默认上限数值吻合（1MiB ≈ websockets.sync.client 默认 max_size），且失败表现为连接被关闭而非解析/语义错误——这一事实在 event_stream 的建议原文里第一跳就已暴露，足以把根因空间从"语义层/解析层/全仓任意处"缩为"该组件传输层连接构造点是否漏传参数"。

## Short path
- 读权威记录（exec record + event_stream）一次性提取：命名工具、精确阈值、失败签名；此后不再做无导向搜索
- 由工具 registry 把命名工具映射到实现文件，仅在该组件路径内定向 grep 连接构造点（websocket_connect/max_size/open_timeout 等），同型通道（只读与 mutation）一并对齐
- 读构造点源码，确认可疑参数是否使用库默认值；确认即锁定根因
- 在构造点参数化修复（默认值+env 可调）并让断连可重连不困死；按报告的原始复现阈值（>1MiB 大页）+新增单测验证
- 回归绿、exec 记录更新后停止；不重放上一会话的宽搜索（如全仓内容检索、无关 EVO id 检索、错误路径 glob）

## Stop conditions
- 构造点确认已显式传入非默认上限 → 阈值-默认值匹配假设被证伪，此时才扩大到应用层 cap/解析层搜索
- 失败签名不是连接级（无 close/断连，而是 parse/grounding 错误）→ 直接排除帧上限假设
- 复现阈值验证 + 单测 + 回归全绿且任务记录已更新

## Verification
- grep 证明该组件所有连接构造点都显式传帧上限参数且可被 env 覆盖
- 在报告的原始复现条件（超大页 snapshot）下：新默认成功、旧默认干净失败且断连后可重连同一 target
- 新增参数有单测覆盖；全量回归通过后任务记录状态更新

## Counterexamples
- 阈值不匹配任何已知库默认（如 200KB 处失败）：根因更可能是应用层 cap（如 node_cap 截断），本捷径会误导
- 错误是解析/语义层异常（JSON 截断、grounding 失败，无连接关闭）：帧上限假设不成立
- 依赖库被 vendored/patched，"默认 1MiB"先验失效：必须读实际捆绑实现再判断
- 证据只有模糊症状（"页面大了就坏"）无精确阈值：缺少可匹配的 discriminator，需先做定位性搜索而非直接跳构造点
