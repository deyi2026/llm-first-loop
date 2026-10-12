---
method_id: deploy-acceptance-follow-change-identity-b334d83e67f1
name: deploy-acceptance-follow-change-identity
description: 部署/重启验收时，若部署状态或回执已给出明确变更标识（git_head/commit/generation），功能层验收应沿该标识走：查看该 commit 改动的文件，运行覆盖这些文件的针对性测试；而不是先枚举 scripts/tests 目录找通用冒烟脚本（本次踩到烧 API 配额的无关回归脚本、又陷进无凭据的登录死路，共浪费 3~4 次探测后才转向）。运维面（进程/端口/入口/回执）照常逐项验证；日志以最后一次 startup 标记为界只扫新段，旧错误按行号归因旧进程。凭据不可得的端到端项明确声明为验证缺口并停止，不再继续找替代脚本。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:520:d562a2e60d5bdd1a777a
evidence_refs: learning:learn:d5fde048e05e
created_at: 2026-09-18T13:30:03.441190+00:00
updated_at: 2026-09-18T13:30:03.441190+00:00
---
## Trigger
用户要求对一次发布/重启做验收，且第一个工具结果（部署状态/回执）中已出现变更标识（git_head、generation、commit、版本号），同时验收清单点名了具体被修复的行为或子系统（如会话隔离、SSE 不中断）

## Discriminator
变更身份早已在手：第一次工具调用即返回 git_head=696f97268 + generation=29，且验收项点名具体子系统。这两点当时已把『如何做功能验证』收窄为『看该 commit 改了哪些文件 → 跑覆盖这些文件的测试』，无需泛搜通用 e2e 脚本

## Short path
- 读部署状态：确认 generation/git_head 与发布期望一致，记下变更标识（未知量：这次部署到底改了什么）
- ps 过滤出本次新起进程 PID；lsof 只按该 PID 查监听端口，不做全端口宽列（未知量：新进程是否健康、web 端口是哪个）
- curl -sL 跟随重定向探入口（未知量：WebUI 是否可达，303→login→200）
- 按当前时间窗 grep 重启回执：三服务 rc=0、时间晚于发布点（未知量：重启是否全部成功；早于发布的失败回执直接归因历史）
- 定位日志中最后一次 startup-complete 行号，只扫其后新段（未知量：新进程是否零错误；ref collision/shutdown 异常按行号归因旧进程）
- lsof -p 桥进程查上游 ESTABLISHED（未知量：桥是否真活着，stdout 缓冲不可信）
- 由变更标识列出改动文件，运行覆盖这些文件的针对性测试作为功能证据；无登录凭据的浏览器端到端项明确列为缺口并停止找替代脚本

## Stop conditions
- 部署标识=发布期望、新进程健康、入口可达、回执全 rc=0、最后启动标记之后的日志段零错误、改动文件的覆盖测试全过
- 遇到必须有凭据/真实账号才能闭环的端到端项（如浏览器登录）→ 声明验证缺口并停止，不再枚举脚本目录找替代路径

## Verification
- 回执 git_head、部署状态 git_head、发布期望三方一致
- 日志中发现的错误行号均早于最后一次启动标记（归因旧进程而非新进程）
- 实际运行的测试选择器与该 commit 改动文件集有交集（测试确实覆盖被改子系统）

## Counterexamples
- 部署状态不含变更标识（无 git_head/版本），或真实改动未提交、不在这个 commit 里 → 变更身份路线失效，通用冒烟脚本或黑盒探测才合理
- 验收纯属运维面（进程在、端口听、HTTP 200）→ 做代码级测试考古是浪费
- 仓库有强制性的标准验收门脚本（不论改动都必须跑）→ 直接跑它，不必做改动映射
- 改动文件没有任何覆盖测试 → 该路线断裂，退回端到端/手工探针
