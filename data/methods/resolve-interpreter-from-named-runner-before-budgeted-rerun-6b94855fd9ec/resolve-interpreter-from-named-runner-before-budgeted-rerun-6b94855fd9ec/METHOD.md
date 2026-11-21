---
method_id: resolve-interpreter-from-named-runner-before-budgeted-rerun-6b94855fd9ec
name: resolve-interpreter-from-named-runner-before-budgeted-rerun
description: 硬只读预算的复审中，凡需实跑项目测试作裁决时，第一执行槽不得兼作环境试错。被裁决的原始结论由某个具名运行/门禁脚本产生，且该脚本名在任务书或 diff 回执中已可见——先按该脚本自身的解释器与 PYTHONPATH 选择规则一次性解析出权威环境，再用它执行定点测试；导入期失败默认先怀疑解释器错配而非候选回归，只有权威解释器下复现才升格为代码证据。系统默认解释器是最低优先级兜底，不是探索起点。
aliases: 跑测试前先确认项目用哪个python, worktree 共享主区 venv 怎么配, 测试导入失败是解释器问题吗, 系统 python3 跑不动项目测试, 审查实跑用哪个虚拟环境
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:411585bf-ea03-4897-834c-cfd1506e1cca:0:4d3b4a2c2a56593dc4ba
evidence_refs: learning:learn:e9403b3d4756
created_at: 2026-11-17T18:10:26.423130+08:00
updated_at: 2026-11-17T18:10:26.423130+08:00
---
## Trigger
预算受限的只读复审要求实际运行测试/命令作裁决，且项目环境非平凡（worktree、多 venv、门禁脚本自带解释器选择规则），执行前『用哪个解释器、PYTHONPATH 指向哪棵树』尚未解析。

## Discriminator
进入执行前已可见：正在裁决的那次原始运行由某具名门禁/运行脚本产生（本集 diff 回执中的结果文档明写该脚本名），该脚本的选择规则就是权威环境出处；同调用还可确认 worktree 本地无 .venv，裸 python3 兜底必然命中系统旧解释器。

## Short path
- 先合并式完成 git 身份核对（HEAD/status/祖先/diffstat），环境未知量此时不动
- 读精确 diff 时顺手记录回执中点名的权威运行脚本与原结果口径
- 把环境解析并入既有 grep：读该脚本的解释器与 PYTHONPATH 选择规则（如主检出区 venv + 本树 src）
- 用解析出的解释器一次性定点实跑点名测试与 lint；导入/收集失败仅在该权威解释器下复现才计为候选问题
- 全部验收事实（SHA 面、修复闭合、实跑 rc、状态清洁）到手即出终态裁决并停止

## Stop conditions
- 权威解释器解析成功且点名套件在其下实跑完毕，rc 与结论已取得
- 任务只含与环境无关的核验（git plumbing、静态 grep、哈希校验），无需解析环境
- 权威脚本缺失或不可读：退回声明性核验，并在裁决中明确标注『未独立复跑』而非默写其结论

## Verification
- 实跑解释器版本与脚本选择规则的输出一致（如 3.13.x 而非系统旧 3.9），导入与收集零错误
- PYTHONPATH 指向被审 worktree 自身的 src，而非安装锚定的旧代码树
- 测试前后 worktree status 均干净，实跑未改变被审状态

## Counterexamples
- 任务与产物都没点名任何权威运行脚本、仓库也无 venv/锁文件标记：试跑默认解释器是正当探索，不要凭空发明权威环境
- 待执行命令与环境无关（纯 git plumbing、静态 grep、哈希校验）：直接执行，先读脚本反而浪费槽位
- 具名脚本本身就是被审对象（如审查门禁脚本是否作弊）：其选择规则不可作为己方执行的权威，应改从 pyproject/锁文件推导要求
- 预算宽松且默认解释器已知满足项目 requires-python：直接执行即可，解析读取不划算
