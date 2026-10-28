---
method_id: audit-change-completion-across-written-verified-live-layers-08d83466d403
name: audit-change-completion-across-written-verified-live-layers
description: 被问『这次改动完成了吗』时，不要只凭代码写完+测试通过下结论：把完成度拆成三层各取一份当次权威回执——written 层看 VCS delta（未提交≠已发布）；verified 层看最近门禁与独立复审的最终回执（REVISE 后必须有后续 PASS）；live 层看运行时地面真值（服务进程启动时间 vs 代码修改时间、状态文件 updated_at 是否持续推进、线上 API 是否出现新字段）。数据指标达标可能来自手工补齐而非新机制产出：pending=0 须用调度器状态归因到新代码路径才能宣称闭环生效。历史根因叙事对回答『完成没有』不必要，不要为此对会话 evidence 反复换措辞搜索。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7fa91553-3285-4608-a1bc-56326b46bea9:1046:9e7a2c5bc26d7676d3fc
evidence_refs: learning:learn:fec955827b73
created_at: 2026-10-17T22:14:18.544106+08:00
updated_at: 2026-10-17T22:14:18.544106+08:00
---
## Trigger
用户询问某个已实施的代码改动『改完没有/完成了吗/能收官吗』，且改动横跨代码、门禁/独立复审与常驻运行时（Web 进程、后台定时器、状态文件），无活动 goal 需快速重建状态并给裁决

## Discriminator
三条当时即可见的判别事实：(1) git status/diff 回执——17 个修改+2 个新增文件全部未提交，直接定义改动面并排除『已发布』；(2) runner_state.json——last_attempt(22:02) 与 last_success(20:43) 分离且 skipped=no_pending，说明数据完整但无法证明新调度在跑；(3) 验证回执——tier0 319 passed 但复审为 REVISE 且修复后无第二份 PASS。任何单层事实都不足以回答『完成吗』，三层合起来即可，无需复原历史根因叙事

## Short path
- git status --porcelain + diff --stat：未知量=改动面与提交状态；未提交/未跟踪文件直接给出『written 但未 shipped』
- 读改动自带的状态工件（runner_state.json、ledger 计数）：未知量=数据是否补齐、由谁产出（last_success vs last_attempt、skipped 原因区分手工补分与自动巡检）
- 核对运行时地面真值：服务进程启动时间 vs 代码修改时间、线上接口响应是否含新字段：未知量=新机制是否真的在跑
- 一次检索最近门禁与独立复审回执（job_output evidence 单次命中即可）：未知量=verified 层是否收口（REVISE 后是否有 PASS）
- 分层输出结论：written=是 / verified=否 / live=否，附对应收口步骤；停止取证，不为复原历史叙事继续换措辞搜索 evidence

## Stop conditions
- 三层各有当次权威回执（VCS delta、最新门禁/复审回执、运行时状态文件+进程事实）即停止取证
- 发现任一层未收口（未提交 / 无复审 PASS / 进程未加载新代码）即可下『未完成』结论，无需继续证明其余层
- 对『闭环生效』的正向断言，必须看到新机制自己产出的增量（新回执→pending 升→自动下降并出分），看到即停

## Verification
- 结论中每个『未完成』子项都能指到一份当次读取的回执：git 回执、复审回执、runner_state 时间戳、进程启动时间
- 『已生效』类断言须由新代码路径产出的运行时证据支撑，不得用手工补齐的数据冒充
- 三层裁决相互独立：任一层证据缺失时该层标注 unknown 而非默认通过

## Counterexamples
- 纯库/CLI 改动无常驻运行时：live 层退化为一次真实调用演示，不要去寻找不存在的状态文件或进程
- 用户只问『改了什么』而非『完成没有』：diff 叙事即可，无需三层审计
- 状态文件由新旧代码共享路径写入（手工 CLI 也能更新）时，新鲜时间戳本身不能证明新机制在线，必须叠加进程启动时间或线上 API 结构
- 个人脚本已提交且 CI 绿且无部署环节：written+verified 已足够，不必审 live 层
