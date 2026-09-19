---
method_id: single-live-job-scheduled-recheck-e377df22c7b1
name: single-live-job-scheduled-recheck
description: 长耗时验证（全量测试/大构建）转后台后，若命令输出经过 tail 类终止过滤，完成前轮询按构造必然 0 行、无任何信息；应保证同一验证只有一个活跃实例，用定时提醒代替轮询，等待期只做与结果独立的审查。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:4d6c551c-a50d-4ef1-90cf-b0af9f557745
created_at: 2026-09-09T18:18:16.818223+00:00
updated_at: 2026-09-09T18:18:16.818223+00:00
---
name: single-live-job-scheduled-recheck
status: candidate
trigger:
  - 长耗时验证（全量测试套件/大构建）前台执行超时，转入后台 job
  - 命令输出经终止过滤器（如 `| tail -N`），完成前查询输出必为空
  - 环境提供定时提醒/完成回调原语
discriminator:
  - 命令串以缓冲过滤器结尾 ⇒ 完成前 job_output 按构造无信息
  - 前台已超时 ⇒ 时长下界已知，远大于秒级轮询间隔
  - 已注册到点提醒回执 ⇒ 此刻再轮询一次不改变任何决策
short_path:
  - 前台超时 ⇒ 推断时长下界；按命令指纹核对无等价活跃 job 后，后台启动一次并记录 job_id
  - 早期轮询一次（只为捕获收集期秒级失败）；若 0 行且 running ⇒ 注册单个定时复查，间隔≈预期时长
  - 等待期只做与该结果独立的审查（如改动 diff 复核）；审查完成且无新未知量 ⇒ 停止动作，等提醒触发
  - 提醒触发后单次读取结果：终态且绿 ⇒ 进入提交阶段；失败 ⇒ 读尾部输出定位，修复后重启一次
  - 需要换参数重跑时，先终止旧 job 再启动新 job，杜绝双实例并行
stop_conditions:
  - job 已终态且结果恰好读取一次
  - 独立审查完成且未产生新的未知量
verification:
  - 同一昂贵验证在任意时刻活跃 job 数 ≤ 1
  - 最终决策（提交/修复）由单次终态读取门控，而非多次轮询累积
anti_patterns:
  - 注册提醒后在同一回合再 poll 一次
  - 因“0 输出像卡住”而再启动一个等价套件（0 输出是管道结构保证的，非卡死证据）
  - 事后 kill 重复 job 收尾，而不是启动前查活跃实例
counterexamples:
  - job 流式输出（无 tail、live log）⇒ 早期轮询有信息，应先 poll 一两次捕获快速失败后再停
  - 套件很快（低于前台超时阈值）⇒ 直接前台跑，无需后台与定时机制
  - 无定时原语可用 ⇒ 按预期时长设置轮询间隔，绝不背靠背连发
  - 等待期工作必须真正独立于测试结果；若审查依赖结果，纯等待才是正确动作
programizable:
  - 命令指纹=剥离尾部过滤器后的规范形；启动昂贵验证前比对活跃 job 的命令指纹，重复则拒绝
  - 检测“命令含尾部缓冲过滤器 + status=running + 输出 0 行” ⇒ 在定时事件或最短间隔前抑制重复 job_output 调用
model_owned:
  - 估计实际时长并与提醒间隔匹配；判断等待期哪些独立审查值得做；失败尾部输出是否值得修复后重跑
why_shorter: 识别出管道结构使完成前轮询按构造无信息，从而删去 N 次空轮询与一次重复的全量执行。
