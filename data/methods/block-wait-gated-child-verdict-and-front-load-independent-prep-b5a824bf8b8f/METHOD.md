---
method_id: block-wait-gated-child-verdict-and-front-load-independent-prep-b5a824bf8b8f
name: block-wait-gated-child-verdict-and-front-load-independent-prep
description: 当已 spawn 的子代理的终态 verdict 是父会话下一步动作（落盘回执、合并、给用户结论）的唯一剩余前置时，不要对同一 child 连续发出同形查询空转。先把所有不依赖 verdict 的父级收尾（时间戳、回执骨架字段、白名单/模型可用性核验）前置做完，再用 spawn 回执中已文档化的最大阻塞等待参数等待终态。连续收到同一非终态回执即视为零新增信息：此时决策只剩『更长阻塞等待』或『按任务书截止条件诚实 STOP』，绝不原样重发同一查询。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7be98f95-f58f-483e-8155-8babb3a24e72:0:3c9965fd09eff78e297e
evidence_refs: learning:learn:8180ae023d8f
created_at: 2026-10-17T06:46:12.229751+08:00
updated_at: 2026-10-17T06:46:12.229751+08:00
---
## Trigger
子代理已被 spawn，其 verdict/终态是父会话下一个动作的唯一 gate；等待 API 存在阻塞参数；父会话仍有少量与 verdict 无关的收尾工作可先做。

## Discriminator
spawn 回执当时已显式文档化阻塞等待能力（wait_seconds=0..30），且每次轮询回执都写明『child 尚未结算；可继续父级工作…或稍后再次查询』。即当时已知：(a) 存在阻塞等待而非只能短轮询；(b) 存在可穿插的父级工作。连续同形的 running 回执不缩小任何未知量，只消耗轮次。

## Short path
- spawn 子代理后，先完成全部不依赖 verdict 的父级动作：取当前时间戳、起草回执的静态字段（goal_id/branch/commits/merge_mode 等）、确认工具白名单与模型可用性。
- 用文档化的最大阻塞等待参数等待子代理终态，而不是立即发起短查询。
- 若回执仍为同形非终态：不重发相同调用；要么再阻塞等待一轮，要么按任务书规定的诚实 STOP 条件（如子模型不具资格、空输出）停止并如实上报。
- 取得终态 verdict 后，一次性填入 verdict/tested-commit/child id 等字段并落盘回执、执行被 gate 的动作。

## Stop conditions
- 子代理进入终态（completed/failed/cancelled），立即退出等待循环，不再查询。
- 触发任务书的诚实 STOP 条件（子模型不具备资格、空输出等）：停止重试并上报，不刷重复调用。
- 连续约 3 次同形非终态回执且父级已无任何可做工作：转为一次长阻塞等待或 STOP，不再短轮询。

## Verification
- 复盘轨迹：同一 child 的等待调用中，不应出现 3 次以上中间无任何父级工作的同形 running 回执。
- 所有依赖 verdict 的产物（回执落盘、合并声明、最终答复中的 PASS/REVISE/BLOCK）在时间上均晚于终态取得。
- 若走了 STOP 分支，留有明确上报记录而非静默重试或重 spawn。

## Counterexamples
- 子代理预期秒级返回且父级确无任何可做工作：一次短查询后转阻塞等待即可，本方法不改变结果。
- 运行时的阻塞等待会独占整个会话、且父级有紧急独立工作（如用户正在等回复）：短轮询并穿插工作才是正解，不应死等。
- 子代理有已知挂死失败模式且任务书设了硬截止：无界长阻塞等待浪费墙钟时间，应改为有界轮询并按时诚实 STOP。
