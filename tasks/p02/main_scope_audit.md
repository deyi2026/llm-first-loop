# 主区记忆 scope 审计清单 v2（修正版，按 DECISION §1 永久排除法）

总条目 536 | 现状 global=509/session=27

## A. 建议新增 session（6 条，现为 global）

- MEM-20260810-04be7b27 [fact] 现=global ['重启/授权'] | web.log 中 [CACHE-DBG] 前缀哈希打点（m0/m1-5/m6-20/m21-60/m61+、
- MEM-20260811-9dde9612 [fact] 现=session ['进程/运行'] | CLI 进程（PID 57246，12:04AM 启动）仍运行旧代码，未加载会话分支/工具并发/压缩主动化/S
- MEM-20260811-aec53cb5 [fact] 现=global ['重启/授权'] | 服务重启注意事项：重启web/feishu会中断进行中的飞书长任务（如om_x100b671e），需先确认；重
- MEM-20260813-0de32524 [fact] 现=session ['进程/运行', '重启/授权'] | 2026-08-13 重启后 feishu(PID 74636, 09:04) 与 web(PID 69462
- MEM-20260813-8d37efa4 [decision] 现=session ['进程/运行'] | 2026-08-13 用户授权 AI 执行 web/feishu 重启：先重启 web（HTTP 零风险，69
- MEM-20260820-188b7dc9 [fact] 现=session ['进度快照'] | batch13 进度：13810 已完成（patch 落盘 /tmp/swe_lfl_patches/djan

## B. 现 session 27 条处置（按判例：19→global、4 去重、~4 保留）

- MEM-20260810-900d32e1 [fact] pylint SWE-bench Verified 终验里程碑：10 实例全部 resolved（10/10）
- MEM-20260810-4bd1e04e [fact] 用户飞书身份映射：open_id=ou_8fc14b9345399c1cffe7f6173afd0f49 对应
- MEM-20260810-24c87f84 [fact] 2026-08-13 用户重启 feishu(PID 74636)/web(PID 69462) 后，P1系列
- MEM-20260810-0ee19b6b [fact] 当前生效配置（EVO-20260818 基座 + 8-19 方案A修复 + 两全方案）：REASONING_T
- MEM-20260811-9dde9612 [fact] CLI 进程（PID 57246，12:04AM 启动）仍运行旧代码，未加载会话分支/工具并发/压缩主动化/S
- MEM-20260811-6c2afbef [fact] 操作教训：验证 CLI fork 命令时，因清理逻辑用 ls -t | head -1 取最近文件，fork 
- MEM-20260812-77b6133b [fact] 2026-08-13 09:04 用户重启 feishu(PID 74636)/web(PID 69462) 
- MEM-20260812-d7535179 [decision] 已实施 M47 飞书桥防假死修复（commit 262298c，main，7 文件 +283/-9）：brid
- MEM-20260813-7c44d35d [decision] 【交接清单·P1系列+用户待办核查】目标: 验证外部遗留改动 + 核查用户原始待办。已完成: ①P1-1/P1
- MEM-20260813-0de32524 [fact] 2026-08-13 重启后 feishu(PID 74636, 09:04) 与 web(PID 69462
- MEM-20260813-d4addc9b [fact] 存在旧代码长驻进程：feishu(pid=1802) 与 web(pid=1773) 启动于旧 HEAD 76
- MEM-20260813-8d37efa4 [decision] 2026-08-13 用户授权 AI 执行 web/feishu 重启：先重启 web（HTTP 零风险，69
- MEM-20260816-75c07e10 [convention] 长回答易被上下文预算截断导致内容丢失；应先将完整内容写入本地文件（如 /tmp/reports/ 目录），再向
- MEM-20260816-6b9698fc [fact] 长回答易被上下文预算截断导致内容丢失；应先将完整内容写入本地文件（如 /tmp/reports/），再向用户发
- MEM-20260816-13e627b9 [convention] 长回答防截断策略：长回答易被上下文预算截断导致内容丢失，应先将完整内容写入本地文件（如 /tmp/report
- MEM-20260816-967ea3ca [decision] 长回答/长报告防截断约定：先将完整内容写入本地文件（如 /tmp/reports/），再向用户发送精简摘要并附
- MEM-20260818-ee4464c6 [fact] requests 8 实例评测纪律（2026-08-17 对照实验）：全程不看答案（无 gold patch、
- MEM-20260818-27588cce [decision] 用户批准执行 kill + 修脚本：mock harness 残留进程 57420/57422（/tmp/ru
- MEM-20260818-f199f134 [decision] 2026-08-19 缓存命中优化：TOOL_TAIL 16→64、REASONING_TAIL 2→0（.e
- MEM-20260819-74372bb6 [fact] SWE harness 经验：swebench v5 的 run_instance 返回 (instance_
- MEM-20260819-4516fe70 [fact] swE-bench django__django-11734 官方修复为 Django PR #11734 /
- MEM-20260819-0232f98a [fact] 2026-08-19 两全方案落地状态：.env 备份 .env.bak-twofold-20260819-2
- MEM-20260820-188b7dc9 [fact] batch13 进度：13810 已完成（patch 落盘 /tmp/swe_lfl_patches/djan
- MEM-20260820-0e2c227a [fact] 2026-08-18 与 DSH 确认（021+11）：模拟数据降级为辅助，deepseek 高命中核心是结构
- MEM-20260820-7c33159f [fact] django__django-13820 官方修复对应 Django PR #13820 / Fixed #3
- MEM-20260820-7902a8e1 [fact] 截至 2026-08-20，Django batch10 与 batch11 已由官方 harness 验证 
- MEM-20260820-5010d4f1 [fact] SWE-bench 任务盘点（截至 2026-08-20）：已完成的 Django 批次以 /private/

## C. 根因记录

镜像两次打标被覆盖：web 进程加载旧内存态（工作区未 commit + 进程未重启），裸写文件被回滚。打标须经 MemoryStore API 或停进程后写 + 重启验证。
