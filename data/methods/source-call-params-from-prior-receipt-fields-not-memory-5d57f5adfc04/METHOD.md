---
method_id: source-call-params-from-prior-receipt-fields-not-memory-5d57f5adfc04
name: source-call-params-from-prior-receipt-fields-not-memory
description: 接手/续跑一个本会话已有成功回执的受管任务（服务重启、git/闸操作）时，把第一条成功回执当参数事实表：绝对路径、参数字段契约、覆盖面注释、异步终态核对入口都已打印在字段里。发起任何新调用前，把记忆性取值（workdir、参数字段名、目标清单）逐项对表：已入表直接引用；未入表且工具提供 get_tool_schema 就先读一次 schema 再调用；两者皆无才允许试探。避免三类同根失败：凭记忆猜 workdir 导致目录级报错重试、参数契约不符被拒、以及用印象代替回执里的覆盖面事实（如整单重启不含某服务）。用已打印字段把记忆候选空间压成零猜测调用，省掉失败重试与超时搜索。
aliases: workdir从回执抄不要靠记忆猜, 调用不熟悉的工具先读一次schema, 接手会话先把回执当参数表对一遍, 路径就在第一条status回执字段里, 参数契约别凭印象填字段名, 整单重启的物理覆盖面看回执注释
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d7d570d1-4d88-404b-9c9e-79d8afafaeed:1406:dce977dc930902e98dfd
evidence_refs: learning:learn:907b9b8d8dc1
created_at: 2026-11-15T19:52:05.255714+08:00
updated_at: 2026-11-15T19:52:05.255714+08:00
---
## Trigger
接手/续跑一个已有成功回执在手的受管任务，需要发起新的工具调用：shell 命令的 workdir/cwd、控制面 action 的参数字段、对异步动作的核对，或按覆盖面缺口补动作

## Discriminator
拟填入调用的每个记忆性取值，能否在本会话已有成功回执的字段/注释里找到原文——绝对路径字段、必填参数 enum、覆盖面分区注释、next_check 终态入口通常都在第一份 status 回执里；找不到且工具带 schema，则 schema 是第二权威源；两者都无才允许试探

## Short path
- 开局读一条权威 status/回执，建立参数事实表：绝对路径、字段契约提示、覆盖面分区、next_check 终态入口
- shell 调用的 workdir/cwd 直接抄回执里的绝对路径字段，不写记忆路径
- 首次调用不熟悉的 action 前先 get_tool_schema 一次，按 schema 构造实参（必填字段与 enum 一次填全）
- 覆盖面注释指出缺口（如整单重启不含某服务）→ 按注释补单独动作，不从日志枚举重推
- 代码定位优先具名 provenance：已知实现提交则 git show --stat 拿文件清单 → 符号索引 grep → sed 定点精读，不做全库内容搜索
- 异步动作以回执 next_check 指定入口核对终态，受理不等于完成

## Stop conditions
- 所有调用实参都能追溯到本会话回执字段或刚读的 schema 原文
- 异步动作经指定入口查到 succeeded/failed 终态且断言成立
- 用户所需事实已被权威来源验证即停，不再补确认性调用

## Verification
- 后续调用不再出现『不是有效目录』『参数契约不满足』这类回执字段本可直接预防的失败
- 终态核对走回执给出的 action_id 查询入口，断言（如 status=succeeded、收敛不再滞后）成立

## Counterexamples
- 回执是纯日志流、不含路径或契约字段（如匿名 tail 输出）→ 无表可对，须另行发现路径，本方法不适用
- 本会话已成功调用过同一工具同一参数形态 → 直接复用上次实参即可，重读 schema 是仪式性浪费
- 任务目标本身就是探明未知内容在仓库的分布（无具名提交、无已知标识符）→ 内容级搜索是正路，provenance 捷径不存在
