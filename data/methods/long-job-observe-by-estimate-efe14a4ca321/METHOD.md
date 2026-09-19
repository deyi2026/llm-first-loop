---
method_id: long-job-observe-by-estimate-efe14a4ca321
name: long-job-observe-by-estimate
description: 启动长时运行、需要观察进度的实验/批处理命令前，先用'步数×单步时延'估计总时长来决定同步/后台与轮询节奏，并强制逐行输出可见，避免超时、缓冲误杀与重叠轮询。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T17:57:09.577688+00:00
updated_at: 2026-09-09T17:57:09.577688+00:00
---
name: long-job-observe-by-estimate
status: candidate
trigger:
  - 即将运行由多次串行外部调用（真实 API/网络/子进程）组成、总时长分钟级的脚本
  - 需要在后台任务上观察增量进度并汇报结果
discriminator:
  - 启动前即可计算：脚本含 N 次串行调用 × 单次秒到几十秒 ⇒ 总时长超过同步命令超时，必须后台化
  - stdout 重定向到管道时按块缓冲；print 无 flush 则后台任务长时间'无输出'是假象而非挂起
short_path:
  - 起跑前用 N_calls×单步时延估计总时长，超出同步超时 ⇒ 直接 run_in_background + 强制逐行刷新（-u/PYTHONUNBUFFERED/flush=True）
  - 首次轮询读出已完成的 k 轮 ⇒ 下次检查点 = 剩余轮数×实测单步时延；同一任务同时只保留一个待触发提醒
  - 轮询返回零新行：若 elapsed << 估计 → 间隔加倍退避；若 elapsed >> 估计 → 转入挂起诊断（查状态/子进程），而非更快轮询或杀任务
  - 杀死'静默但 running'的任务前，必须先用 elapsed-vs-估计 排除块缓冲假象，避免整轮真实调用白跑重跑
  - 状态 done 后完整输出只读一次，进入分析并停止观察
branch_on_evidence:
  - observation: 轮询输出与上次完全相同且远未到估计完成点
    next: 拉长检查间隔，不叠加新提醒
  - observation: 输出停滞且 elapsed 远超单步估计
    next: 诊断挂起（状态/CPU/网络），而不是重跑
  - observation: 单步实测时延与预估偏差大
    next: 用实测值重算剩余检查点
stop_conditions:
  - 任务 done 且完整输出已读一次
  - 或挂起已确认并处理（终止/修复），不再对同任务注册新提醒
verification:
  - 每次有效轮询应至少带回一行新进度，否则间隔设计有误
  - 同一 job 的 pending 提醒数 ≤ 1；被杀任务在杀死前已有'非缓冲'证据
anti_patterns:
  - 同步运行可预知分钟级的串行调用脚本
  - 后台跑 python 进度脚本却不加 -u，把'看不见输出'当成挂起杀掉重跑
  - 为同一任务叠加重叠 schedule 提醒并即时重复 job_output
  - 零新信息时缩短而非拉长下一次检查间隔
counterexamples:
  - 单次快速调用或秒级脚本：同步直接跑，后台+轮询反而是开销
  - 进度已写入带 flush 的日志文件或任务自带心跳：无需 -u，按心跳节奏检查
  - 时长高度不可知且用户实时等待、轮询代价极低：紧凑轮询可能合理，估计驱动退避不再占优
  - 轮询无新行但 elapsed 已远超估计：应诊断挂起，而非继续退避
programizable:
  - 解析脚本统计 N_calls；用首次观测的每步时延计算下次检查时刻
  - '输出与上次完全相同'事件 → 间隔×2；同 job pending 提醒计数≤1
model_owned:
  - 判断静默源于缓冲还是挂起、时延估计是否可靠、进度数据是否已足以停止观察并转入分析
why_shorter: 把'任意间隔反复试探+重叠提醒'换成由步数与实测时延导出的确定性检查点，并消除因缓冲假象导致的整轮重跑。
