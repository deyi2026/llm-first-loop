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

以上是首次上线前的隔离候选验收。随后用户明确授权 Web 上线测试，生产记录见下节。完整 CI 仍存在可复现基线债务，不宣称 CI 全绿。

## 2026-10-07 生产首次验收暴露的补充根因

首次 gen190 实测恢复委派后，模型输出了 marker，但提醒未 ack，私有授权仍为 pending，因此验收判为失败并撤销两条测试提醒，Web 回退至基线 gen191（相邻服务保持原进程）。真正原因是混合版本共享写入：旧 Feishu/Learning 的 ScheduleStore 每 tick 重读并按旧 schema 全量序列化，丢弃 `scheduled_trigger_at`、`wake_delivery_state`、`wake_wait_reason`。重试时原定时刻变为退避时刻，授权 scope 校验失败；SessionLifecycle 的历史 accepted callback fail-open 又吞掉该异常，仍继续调用模型。

补充修复将上述新增投影字段保存在既有私有签名账本内。仅字段缺失且签名与原授权 scope 全部匹配时补回；内容、原时刻或签名变动均拒绝恢复，不建立第二调度队列。新旧服务可继续共存。准入回调按签名确定参数数量，只调用一次；任何回调异常在 provider 之前阻断运行，防止“未消费授权却已经执行”。覆盖旧 schema 子进程重写、篡改拒绝、真实 LoopEngine 准入异常（ValueError/TypeError/OSError）以及旧零参 callback 兼容，共新增 8 条回归。

全量补充检查还发现普通提醒在无私有账本时误入新增 fcntl 路径，影响既有非 POSIX 文件锁回退。无账本时投影恢复/保存现在直接返回，普通提醒保持既有回退；scheduler 与授权恢复定向 46 项通过。

补充修复最终代码验证 tree `8b1cb5b17c171ff97634d155e319230d45e1e490`：全量非 real_llm `7599 passed, 116 skipped, 16 deselected, 3 failed, 5 errors`（317.28s），剩余恰为已在精确 af480 基线复现的 3 个 HOME 安全断言和 5 个 Chromium 缺失 setup errors，无新增失败。定向 112 passed，scheduler/fallback 46 passed，规则/提交/epistemic 守卫 45 passed，runtime-cycle/local-import 14 passed；新增恢复测试累计 26 条。Ruff 58、Pyright 44 与基线诊断多重集完全一致，改动范围 Ruff、compile、diff、安全扫描和 A.5 精确 17-path 覆盖通过；WebUI TS/Vite 重新构建通过。此回执仅在验证后追加，代码与验证 tree 一致。生产重新验收须另核对 managed restart 的 succeeded 以及真实 GLM run.end completed，一次 started、无待执行条目，不能从 marker 单独推断成功。

## 混合版本到点认领竞争

gen192 实机复测继续失败，但这次没有调用模型：审计精确定位旧 Feishu 原进程抢先 claim 重启前 owner 已死亡的提醒，在 16:10:00、16:10:30、16:11:30 连续写 `grant_lost_owner_dead`。新 Web 只有抢到到点 claim 才能进恢复分支，因此可被旧线程持续饿死。该测试提醒已取消，独立忙时验收因前置未通过而未启动。

补充修复在 `claim_due` 的到点判断之前验证并接回死 owner 的 pending 委派，登记新 PID 和进程内凭据。未来提醒在此阶段仍不准入、不调用 provider；旧消费者复用既有 alive-owner 规则自动跳过。活 owner、范围/签名不符、取消或已消费记录不接管。新增 4 条回归，含独立旧消费者的所有权判断，定向 scheduler/恢复/factory/API/stream 共 136 passed。保留相邻旧服务作为生产复测条件。

到点前接回修复的最终代码验证 tree `635cb454a4d28cc426144c62b8fa0c7f61649752`：全量非 real_llm `7603 passed, 116 skipped, 16 deselected, 3 failed, 5 errors`（326.15s）。剩余失败/错误与精确 af480 基线集合相同，无新增；提醒恢复新增回归累计 30 条。定向 136 passed；scoped Ruff、Pyright 无新增诊断、A.5 精确 17-path、diff 与安全扫描通过。此回执在验证后追加，代码与验证 tree 一致；生产 v3 验收独立记录。
