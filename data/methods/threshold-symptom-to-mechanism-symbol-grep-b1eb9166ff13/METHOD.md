---
method_id: threshold-symptom-to-mechanism-symbol-grep-b1eb9166ff13
name: threshold-symptom-to-mechanism-symbol-grep
description: 当故障/进化报告给出精确数值阈值或协议错误码（如"DOM+AX >1MB 即全链路断连"、close code 1009）时，先把阈值映射到底层库默认限制（1MiB == websockets max_size 默认；1009 == Message Too Big），形成"调用点缺参数"假设，再用机制符号（websocket_connect/max_size）grep 代码直达唯一调用点；不要按功能名/文件名通配枚举，更不要复播卡死会话 action_trace 里记录的搜索关键词（那是失败面包屑）。命中后读调用点确认缺参，并检查共享同一传输的兄弟通道（感知 host + 执行 host）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:550:6787405d1c639fc28ee8
evidence_refs: learning:learn:ac5936e2eeb7
created_at: 2026-09-18T03:56:48.665370+00:00
updated_at: 2026-09-18T03:56:48.665370+00:00
---
## Trigger
故障报告、进化建议或事件流已包含精确失败阈值或协议层错误码，需要在大代码库中定位实现代码与根因（定位点未知）。

## Discriminator
报告中的失败阈值是否精确等于某底层依赖库的默认限制（例：>1MB 断连 ⇔ websockets 库 max_size 默认 1MiB；1009 ⇔ 帧过大）。若相等，搜索空间从"所有功能相关文件"收缩为"少数 websocket/传输 connect 调用点是否缺该参数"。此判别在读取报告原文那一刻即可获得，无需任何代码枚举。

## Short path
- 完整读取报告/事件原文，提取三个未知量的初始值：失败的具体操作（snapshot）、精确阈值（>1MB）、错误形态（连接被关/1009）
- 把阈值/错误码映射到候选库默认值，形成假设：某 connect 调用点未传帧上限参数
- 用机制符号（websocket_connect、max_size、ws://）grep 源码树，列出全部调用点，而非按功能名（browser、projection_limit）搜内容或猜文件路径
- 逐个读调用点（含共享同一传输的兄弟通道，如感知 host 与执行 host），确认缺参即根因
- 在阈值处复现验证：默认值干净失败、调参后成功；随后停止发现，进入实现与回归

## Stop conditions
- 机制调用点已全部读取且默认限制值与报告阈值精确吻合，根因唯一化
- 或假设被证伪（阈值不匹配库默认）→ 切换到应用层常量分支，不再扩大机制 grep

## Verification
- 确认库默认值 == 报告失败阈值（数值级吻合，不是量级近似）
- 阈值复现测试：默认参数在阈值处干净失败、参数化后成功
- grep 命中的调用点数量 == 已读调用点数量（兄弟通道无漏检）

## Counterexamples
- 失败阈值不等于任何库默认（如 3.7MB 才失败）→ 更可能是应用自身 cap，应 grep 应用常量而非传输库
- 报告无精确阈值、失败间歇或与环境相关 → 阈值映射不可用，必须先复现
- 多层同时设限（应用 node_cap 与传输帧限并存）→ 单一症状无法区分层次，须读完两层调用点才能定根因，不能只修一层就宣布完成
