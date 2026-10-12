---
method_id: resolve-operational-params-from-pipeline-mechanism-not-value-sweep-f64e334cb9b8
name: resolve-operational-params-from-pipeline-mechanism-not-value-sweep
description: 当缺失的是一条既有本地管线的运行参数（收件 ID/端点/绑定关系）时，从该管线自身的入口读取参数解析规则——配置文件、产线源码模块、或活运行时状态接口——而不是用猜测关键词在 records/全库文件里枚举参数的值。核心区分：事件史回答'发生过什么'，当前绑定回答'现在是什么'；收件人这类当前状态只存在于 config/code/runtime state，历史记录里最多留下过期投影。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:62ab768f-1c8b-4c05-baa1-c1ac5d5dd147:96:6b552fa616f22ade8cb5
evidence_refs: learning:learn:8b214e41e8ca
created_at: 2026-09-20T17:09:22.454047+00:00
updated_at: 2026-09-20T17:09:22.454047+00:00
---
## Trigger
需要把产物投递给某个既有能力/桥接（如飞书发送），但缺少其运行参数；对该参数的直接值搜索首轮失败，且该能力已被证实是本地既有管线。

## Discriminator
当时已见事实：md2pdf SKILL.md 明确把'生成报告 PDF（飞书发送/存档）'描述为本仓库常规链路，且 skill_load 回执给出含 src/skills/tests 的源码仓 code_root——说明收件人解析是这条既定管线自身的状态参数，应查管线的 config/源码/运行时，而非继续对 records 和全库文件做关键词值搜索。

## Short path
- 拆解两个未知量：产物生产（已由 md2pdf skill 解决）与投递参数（收件 ID）；生产与投递并行推进
- 沿已证实的管线边缘做一次定向探测：读飞书桥模块/根配置（如 .feishu.env 及 feishu 相关 json/yaml），或探活运行时的会话/channel 状态接口；未知量：收件人由什么机制解析
- 读取代码或配置点名的绑定源（session→channel 映射 / 运行时会话 API），取出用户绑定的 open_id/chat_id
- 用解析出的 ID 反查一次 outbound 审计回执确认可投递（按 ID 查，不按同义词猜），然后生成 PDF 并发送
- 核验 message_id/success 回执后停止

## Stop conditions
- 从管线自身绑定源取到收件 ID 并经一次独立来源（outbound 审计）核对后，立即进入生成+发送
- 机制追踪在两次探测内得出'值不在本地/由外部注入'即止损，改走运行时接口或询问用户
- 发送回执含 message_id 且 success，未向其他会话投递

## Verification
- 发送前：收件 ID 与管线绑定源一致，并有第二独立来源（该 ID 的历史投递成功回执）交叉确认
- 发送后：回执 message_id 存在且 success
- 过程计数：收件解析相关工具调用应≤5；同一查询工具连续第 3 次换关键词且为空即触发止损

## Counterexamples
- 用户请求里已直接给出收件 ID/目标地址：无需机制追踪，直接发送
- 所需参数确实是历史事件（如'上次发给谁了'）：records/audit 才是权威源，值搜索是正确做法
- 本地完全没有该能力的管线/凭据（如仓库无邮件发送代码）：机制追踪无落点，应询问用户或做显式 broad discovery
- 管线配置由外部 secret store 注入且本地不可读：读代码只能得出'值不在本地'，此时应转向运行时接口或问用户，而非继续本地枚举
