---
method_id: trust-durable-completion-evidence-on-resume-ab903c1cdc9e
name: trust-durable-completion-evidence-on-resume
description: 会话中断后恢复任务时，先用落盘的完成哨兵（追加的 EXIT 行、终态进度标记、mtime 稳定）判定后台验证是否在中断前已正常结束且结果仍有效；已被持久证据闭合的未知量不再重验，只闭合真正开放的剩余未知量（如委派规定的提交细节），避免整轮重跑长时验证。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T17:29:47.729378+00:00
updated_at: 2026-09-09T17:29:47.729378+00:00
---
name: trust-durable-completion-evidence-on-resume
status: candidate
trigger:
  - 会话/用户中断后恢复任务，且存在先前启动的后台验证任务（全量测试/构建）待确认
  - 正准备重跑长时验证，或准备查询后台进程存活状态
discriminator:
  - 后台任务的落盘日志已含完成哨兵：命令末尾追加的 EXIT=<code>、[100%] 类终态进度，且文件 mtime/大小稳定不再增长 -> 任务在中断前已正常结束，记录结果仍有效
  - 工作区指纹（git status/diff）与该次绿跑所测试的文件集一致，且被测源文件 mtime 不晚于日志 mtime
short_path:
  - 恢复时先盘点：哪些未知量已被落盘证据闭合（EXIT 哨兵+完成标记+零失败标记），哪些仍开放
  - 「后台任务是否结束」只看日志哨兵与 mtime 稳定性，不做进程存活查询；ps 类工具被沙箱拒绝不构成「进程已死」的证据
  - 哨兵在且绿证据齐 -> 门禁视为满足，跳过重跑
  - 只闭合真正剩余的未知量（如委派的提交文件清单与提交说明），用一次定向检索取回委派原文
  - 按显式清单暂存、核对暂存集与清单逐一匹配后提交并报告，停止
branch_on_evidence:
  - observation: 日志含 EXIT=0 哨兵 + 终态进度 + 零 F/E
    next: 门禁已满足，直接进入下一阶段（提交），不重跑
  - observation: 无哨兵、日志截断在进度中段或 mtime 仍在变
    next: 任务可能中途被杀，重跑验证
  - observation: git status 与绿跑测试的文件集不一致（或源码晚于日志被改）
    next: 记录结果不代表当前树，须对当前树重跑
  - observation: 进程查询工具被权限拒绝
    next: 只依赖产物证据，绝不推断「进程丢失」
stop_conditions:
  - 委派门禁（如「若全绿则提交」）已被持久证据满足，且委派要求的文件清单/提交说明已取回 -> 执行后停止
verification:
  - EXIT 哨兵 + 终态完成标记 + 零失败标记（无 F/E 行、无 FAILED/ERROR）三重闭合；汇总统计行被包装层截断时，用进度点计数对齐已知总数替代
  - 提交前核对暂存文件集与委派清单完全一致
anti_patterns:
  - 把「会话中断」等同于「后台任务结果失效」，重跑数分钟级验证去重新确证已三重验证的事实
  - 由 ps 权限被拒推断进程已死
  - 轮询 sleep 超过工具自身超时上限（如 60s），整次调用白费
programizable:
  - 检测「echo EXIT=$? >> log」类完成哨兵与日志 mtime 稳定性
  - 对 quiet 模式测试日志做进度点计数与 F/E 扫描，替代缺失的汇总行
  - 轮询 sleep 钳制到工具超时以内
model_owned:
  - 判断持久证据是否语义上满足委派门禁（「全绿」）、被测树是否就是将要提交的树
why_shorter: 把「是否完成/是否绿」识别为已被落盘哨兵闭合的未知量，省去整轮重跑与多轮轮询，只闭合真正开放的委派细节。
