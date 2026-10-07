# 一次性提醒跨重启恢复

## 事故与职责

本次真实事故有两条链：重启使进程内 wake grant 丢失，提醒只做指数退避；同会话真人 re-arm 后又遇到 session_busy，但旧实现先写 wake_started_at 再申请后台执行，造成未运行的提醒被误认为已消费。界面只根据 wake=true 显示“到点自动续跑”，隐藏等待原因与原定时间。

修复复用既有 ScheduleStore、IngressToken 和 BackgroundRunner 准入回调。提醒被受理、获得后台 handle 和真正取得执行权是三个不同阶段；只有取得实际 run lease 后的 before_start 回调才消费授权并记录 started。会话忙、重启屏障、排队及准入失败均保留尚未消费的一次性提醒，采用既有 10 次 / 30 分钟双上限退避。

## 设置与恢复契约

| 场景 | 设置或操作 | 预期 |
| --- | --- | --- |
| 仅通知 | wake=false | 到点通知，不调用模型 |
| 当前任务一次性自动续跑 | 当前真人 run 中 schedule(wake=true)，repeat_interval=0，max_count=1；RUNNER_BACKGROUND=1 | 同会话一次性执行；新提醒重启后验证账本并恢复既有委派 |
| 修复上线前创建的旧提醒 | 原会话真人再次发起 run，让未消费提醒 re-arm，或显式取消后重新创建 | 未消费旧提醒获得持久委派；已标 started 的旧条目不能自动辨认是真启动还是旧缺陷，不自动恢复 |
| 同会话仍忙 | 等待会话空闲，界面显示等待原因和下次尝试 | 在有界重试窗口内再次申请；超过上限降级通知 |
| 已取消、已启动、Goal 已替换 | 不重新授权该提醒 | 不重复启动；旧快照恢复也不能重放 |

生产数据目录必须保持稳定且可写，私有授权账本和 key 与 schedule.json 共同保留。更换目录、丢失 key、篡改范围或完整性验证失败时不能恢复原授权；原会话真人确认后重新安排。延长 trigger_at 本身不能恢复授权。

## 持久化与授权边界

新提醒创建时先把已批准的范围及 pending 状态写入私有签名账本，再发布可被 claim 的提醒。范围绑定 sid、原会话、消息、原定时间、Goal generation 和 subject_refs；重试时间不改变授权范围。账本及 key 以 0600 保存，写入执行 fsync、原子替换和目录 fsync。独立跨进程锁串行消费；started/revoked 墓碑与提醒条目分离保留，阻止旧 schedule.json 快照重放。

账本不持久化 token 对象。恢复只产生 delegated=True 的同会话一次性凭据，不产生新真人输入，不扩大白名单，不允许周期或递归 wake。私有签名用于检测文件完整性，不承诺抵御具有相同本机账号文件权限的攻击者，也不支持同时回滚整个数据目录后防重放。

为什么模型不能代判：重启前后的进程内凭据和一次消费状态不是语言模型可验证的授权事实；由模型推测会把通知意图或已消费旧条目误变成执行授权。模型仍可调用 cancel_schedule 显式取消、使用 wake=false 只通知，或在新的真实用户 run 内重新安排；没有新增模型语义裁判。

## 验证与上线

真实事故回归涵盖 busy→重试→执行、handle 不等于准入、旧 worker/新 claim、取消与 Goal 替换、签名/范围/key、持久化失败、全新解释器恢复及旧提醒快照重放。Web API 只投影安全的等待状态，不暴露授权材料。界面保留原定时间并另列下次尝试。

调度条目在实际准入后被消费，started 只证明开始，不证明任务成功。任务完成必须从实际 run/job 终态验证；被受理或提醒消失都不是 succeeded 证据。实际准入到模型工作之间发生进程崩溃可能导致任务未完成；一次消费选择避免重复启动，未完成需真人确认后新建委派。

发布前在隔离候选跑全量非真实 LLM pytest、Ruff、Pyright、架构提交覆盖及 WebUI 测试/build。发布后只重启 Web，记录真实 generation/git_head，安排一个低影响一次性提醒，重启后确认 delegated started 与实际终态；旧事故提醒须另行确认/重建。回滚为撤销此提交并恢复旧 Web 发布，保留私有账本以免后续误重放；旧版本提醒仍采用真人 re-arm。

## 隔离候选验收记录（2026-10-07）

基线 commit `af480f80dd5aa2faf042af03fc7462996bb9d2af`；最终代码验证 tree `cb1a3a1f86177232b02a25823fa6e629997f3e43`。本节验收回执在验证后追加，代码、测试、WebUI 与验证 tree 完全一致。

| 检查 | 结果 | 归因 |
| --- | --- | --- |
| 提醒与相邻回归、factory、架构守卫、API、rule_presence_contract | 129 passed | 含 18 个新增提醒恢复回归；真实 LoopEngine/BackgroundRunner 完成；全新解释器恢复及快照拒绝重放 |
| 完整非 real_llm pytest | 7591 passed / 116 skipped / 16 deselected / 3 failed / 5 errors | 3 个 home 路径安全断言及 5 个 Chromium 缺失 setup errors 均在精确基线复现；不是全绿 |
| WebUI 全量测试 | 268 passed / 1 failed | 未修改 EvolutionPanel 安全确认文案测试；精确基线复现同一个失败；提醒目录 11 项全部通过 |
| WebUI TypeScript/Vite build | PASS | 候选构建完成 |
| Ruff | 修改文件 PASS；全树 58 条 | 精确基线 58 条；诊断多重集合比对无新增 |
| Pyright | 全树 44 条 | 精确基线 44 条；诊断多重集合比对无新增 |
| runtime cycle / local-import ratchet | PASS | 初次门禁发现本轮新环与导入增量，已修正依赖方向；无基线扩容 |
| A.5 staged 16-path coverage / security scan / diff-check / compile | PASS | 提交覆盖与无敏感内容；不替代架构语义审查 |

以上是隔离候选的验收，没有合入 main、远程推送、publish 或生产重启。生产跨重启模型唤醒与实际终态尚未验收；保留既有 FR-1 生产观测发布边界。完整 CI 仍存在可复现基线债务，不宣称 CI 全绿或线上闭环完成。
