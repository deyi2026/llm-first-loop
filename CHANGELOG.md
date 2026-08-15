# Changelog（公开变更记录）

> 面向使用者的变更摘要（内部开发过程记录不公开）。版本语义：0.x 内小版本可增补能力，不破坏既有行为。

## v0.5.1（2026-08-15）

### 截断信号与轮次耗尽强化（用户需求批次）
- **放大字数**：`TOOL_SUMMARY_THRESHOLD` 默认 5000 → 12000；输出分层首尾窗口 600/600 → 2500/2500——截断/摘要发生更晚、可见内容更多（硬上限 100K 安全阀不变，信息零丢失语义不变）
- **截断信号行动指引**：`[输出摘要]` 与 `[结果超长，已截断]` 回执附统一指引——继续推理前先把可见要点与待核实缺口提炼记录（推理链或 [[memory]] 记忆块），最终总结纳入；程序只发信号不替 AI 摘要（RULE-AI-00）
- **轮次耗尽决策轮**：耗尽不再直接罐装终止——注入一次 `[轮次决策请求]` 请 AI 归因：① 工具使用错误/空转 → 如实归因 + 正确做法 + 当前结论收尾；② 正常推进 → adjust_strategy 调大 max_iterations（≤500）续跑。决策轮仅一次（per-session 标志）；AI 未调大仍耗竭 → 回到罐装如实终止（程序兜底边界不变）
- **RULE-AI-11 新规则**：截断提炼与轮次耗尽自主归因写入规则真相源（`docs/ai_rules.md`）+ system prompt 嵌入（同步漂移测试覆盖）

## v0.5.0（2026-08-15）

> 安全深化 + 正确性修复批次（代码审计 18 项发现的完整闭环；审计报告与修复计划为本地过程文档不入库）。

### 安全修复（P0）
- **灾难性命令硬阻断 Guard（P0-1/审计发现 #1/#4）**：execute_command 危险命令检测重写为"全串正则层 + shlex 分段子命令层"双扫描——管道/拼接/`rm -rf` 聚合 flag/`find -delete|-exec rm`/`sh -c` 内嵌/`python -c` 载荷（rmtree/unlink/os.remove 等）此前可绕过的形态全部闭合；命中硬阻断 + 审计落盘 `data/audit/safety_blocks.jsonl`（fail-open）。模块职责如实标注为"已知模式硬阻断+审计，非完备沙箱"
- **web_fetch SSRF 重定向逐跳检查（P0-2/审计发现 #2）**：301/302 跳转此前不经私网校验（公网 URL 可跳板打内网）——curl/httpx 双路径改手工逐跳循环，每跳目的 IP 均过内网拦截，超 5 跳如实报 FAIL
- **web_fetch DNS 钉 IP（P0-3/审计发现 #3）**：解析→连接之间的 DNS 重绑定窗口闭合——curl `--resolve` 钉死已校验 IP；httpx 建连后核验对端地址（不符即断连丢弃，GET 请求行已发出的残余如实标注：保护的是回读数据）
- **会话存储跨进程写互斥（P0-4/审计发现 #5/#6）**：Session 保存此前仅进程内锁——CLI/Web/飞书多进程并存可写穿 JSON。现每会话 `<sid>.lock` flock 覆盖"读-改-写"临界区（含 load→append→save 全链），锁不可用如实降级告警
- **引擎跨会话可重入（P0-5/审计发现 #7）**：停滞指纹/overflow 计数/预算预警/快照节流等运行态此前挂在引擎单例上——同引擎多会话并发 run 互相污染（状态串台/停滞误判）。改为 `contextvars` 会话定位 + per-session 状态桶（SSE/ASGI 跨 Context 驱动用值快照还原），registry 双层线程池均做上下文传播

### 正确性修复（P1）与工程补强（P2）
- **子代理会话泄漏（P1-5/审计发现 #10）**：SubAgentRunner 执行前切到子会话但从不恢复——父级后续超长工具结果归档/变更日志归错子会话（串台）。改为 try/finally 保存并恢复注册表会话（显式字段 + `current_session_id` ContextVar 值快照还原，成功/异常/截断路径全覆盖）
- **工具超时线程/子进程泄漏（P1-5/审计发现 #11）**：`_run_with_timeout` 超时后 `with ThreadPoolExecutor` 退出会 `shutdown(wait=True)` 卡到工具自行结束（超时名存实亡），且 execute_command 的 shell 子进程不被终止。修复：超时路径 `cancel()` + 调用工具 `terminate()` 钩子 + `shutdown(wait=False)` 立即返回；execute_command 前台改 `Popen`+`communicate`（独立进程组 + `terminate()` 整树 SIGKILL），超时后 shell 及其孙进程不再残留孤儿（残余无钩子工具的工作线程如实标注：最多存活到工具自身超时/结束）
- **事件日志滚动未接线生产（P1-1/审计发现 #9）**：RotateManager 此前只有 CLI 读段清单在用，`check_and_rotate` 生产无人调用（事件日志永不滚动），且多段迁移检查在锁外有竞态、迁移后追加 seq 从 1 重启。修复：RotateManager 接线进 EventStore.append（大小触发每次查、天数触发 30s 节流）+ 会话级稳定锁 `<sid>.lock` 覆盖"检查+迁移+追加"临界区 + 多段 seq 全局续号 + 引擎 run 末 `check_rotate` 钩子（均 fail-open；未接线存储零回归）
- **fork 工具轮边界对齐（P1-6/审计发现 #15）**：fork 点切在 assistant(tool_calls) 与其回执之间 → 分支继承孤儿声明，下次运行被配对修复伪造 `[程序异常]` 回执。修复：fork 点自动向前对齐到完整工具轮边界，`ForkReport.snapped_fork_point` 如实报告实际生效点
- **tool_calls 配对漏计空 id 回执（P1-6/审计发现 #16）**：配对自检/补齐按"回执 id 非空"计数，存量会话的空 tool_call_id 回执被漏计 → 多补占位（额外 tool 消息无声明 → API 400）。修复：按 id 精确配对 + 空 id 位置兜底，自检与补齐共用同一缺口函数
- **流式断连会话漂移（P1-6/审计发现 #17）**：`run_stream` LLM 流式中客户端断连（GeneratorExit）跳过 loop 末保存 → 事件日志已追加而 session JSON 未保存。修复：部分回答如实落会话（中断标注不伪装完整）+ 事件双轨同步 + 立即保存
- **retire 指引如实化（P1-2/审计发现 #8）**：`read_path_switched` 字段名暗示已切换（实际只写切换指引）。改名 `read_path_ready_to_switch` + 新增 `switch_instructions`（READ_PATH_SOURCE 修改 + 重启两步指引），CLI 打印与回滚提示同步如实（程序不代写用户 .env）
- **providers 配置解析加固（P1-3/审计发现 #12）**：能力标志严格布尔解析（白名单字符串/非法值 warning + 回退默认，不再静默 `bool()`）；context 缺失回退 131072 与 ModelSpec 默认一致；provider/模型双层 try/except——单条非法跳过该条并如实告警，不再拖垮整个注册表
- **模型解析失败可感知（P1-4/审计发现 #13）**：`switch_model` 目标解析 ValueError 不再静默吞掉——warning 含配置模型名与失败原因；`config_status` 新增 `model_registry_resolved` 维度，AI 可感知"模型配置未生效"
- **鉴权 fail-closed + 跨站写防护（P2-1）**：`WEB_AUTH_REQUIRE=1` 未配置 `WEB_API_KEY` 旧实现静默放行（等于无鉴权）——现启动拒绝（对齐远程绑定校验语义）+ 请求期 503 如实报错；回环豁免部署的 mutating 端点新增 Origin 头校验（非回环来源 POST/PUT/DELETE/PATCH → 403，防浏览器跨站打 127.0.0.1；无 Origin 的 curl/脚本不受影响）
- **upload 体积前置检查（P2-2）**：base64 体积先查字符串长度（≈4/3 原始体积）再解码，超限直接 413——大 payload 不再先吃解码内存/CPU
- **会话锁表无界增长 + 首聊竞态（P2-3）**：`session_locks` 改 LRU 上限 1024（淘汰最旧空闲锁，持锁不淘汰防互斥失效）；无 session_id 并发首聊的"取共享→建会话→设共享"收进同一模块级 guard——不再双建孤儿会话
- **LLM 连接泄漏（P2-4）**：`LLMClient.close()` 此前无人调用。新增 `ModelClientPool.close()`（default+缓存全关，幂等）与 `LoopEngine.close()`；`clear_cache()` 热重载路径改为先关旧 client 再清空；CLI 主返回路径、web 退出、飞书停机均接线关闭
- **eval 管道验证补强（P2-5）**：wilson_ci docstring 漂移修复（k=0 正常计算真实区间如 (0.0, 0.562]，仅 n≤0/k<0 返回 (0,0)）；dry 模式新增注入可见性自检（真实状态追踪器注入 FAILURE → architecture_status 快照路径断言可见，不可见即管道失效如实报错）
- **fallback 引擎级集成测试（P2-6）**：真实 `_try_fallback_chain` 触发路径（主模型 500 → 降级链成功）——断言回答来自降级模型、`[模型降级]` 回执注入、architecture_status 降级态与 `model_fallbacks_count` 配置计数可见；4xx 不降级与链全失败汇总两条零回归路径同测

## v0.4.0（2026-08-15）

### 新能力
- **孤儿 tool_calls 合成回执（HARNESS-01）**：`run_stream` 客户端中断（close）时自动写「已取消」合成回执并立即保存——不再产生「有声明无回执」的孤儿声明（严格 FC 协议 400 根源），对账不变量「声明数 = 结果数 + 取消数」
- **`request.meta` 事件（HARNESS-02）**：每轮 LLM 请求快照入事件日志（round/model/thinking/reasoning_effort/tools_count/history_chars/budget），回放可确知"当时用的哪个模型/挂了哪些工具/预算多少"
- **web_fetch SSRF 内网拦截（HARNESS-03）**：`WEB_FETCH_BLOCK_PRIVATE`（默认开）拦截私网/环回/链路本地/保留段地址（IP 字面量 + DNS 解析双路径），命中返回 BLOCKED `[内网拦截]`——防云元数据（169.254.169.254）等内网探测
- **上下文预算预警（HARNESS-04）**：上下文占用率 ≥80% 预算时注入一次 `[预算预警]`（含占用率/字符数），"压缩/收尾"决策归 AI——程序不自动压缩（RULE-AI-00）
- **程序故障指标（R2/A6）**：`architecture_status` 上报程序故障计数（event_write/memory/llm_call/session_persist 等 fail-open 点），AI 可感知"程序故障率"并应对
- **archive-index 存量段索引重建（R3）**：`archive-index` 命令幂等重建历史段检索索引（存量无索引段全文扫描兜底升级为索引检索）
- **飞书显示批次**：超长行零宽空格折行（fence 内不折）+ 分段字节预算（50000→30000 防物理上限）+ 表格降级增强（来源标注/列数提示）+ 摘要卡交互化（「展开全文」命令，消息条数收敛）+ 状态卡 1s 节流 + 发送最小间隔 300ms + 渲染支持矩阵 `docs/feishu_render_matrix.md`
- **本地真实回归脚本**：`scripts/run_real_smoke.sh`（冒烟 + 评测集，key 从 env/.env 读取，`--quick` 模式）——key 不上传策略下的 CI 补位

### 改进
- **工具重名去噪（R1）**：同一对象重复注册静默跳过（修复 `RUN_MODE=minimal` 过滤失效），工具面更干净
- **评测 token 开销指标（A2）**：场景级 tokens_in/tokens_out 聚合 + 报告渲染（`scripts/run_eval.py`）
- **run_mode 文档化（A1）**：`docs/configuration.md` 补 standard/ptc/minimal/creative 模式说明
- **开发方法论公开（B10）**：`docs/development_methodology.md`（SoT 先行/如实记录/零回归/评测纪律）

### 修复
- **上报冷却首调误拦截（HARNESS-05）**：`EventReporter.should_report` 首次调用 last 取 0.0、`time.monotonic()` 从系统启动起算——CI 全新 runner 启动 <60s 时首次上报被误判"冷却中"拒绝，致自我评估/演进提醒偶发不注入（本地系统启动久无法复现，CI 复现；回归测试模拟系统启动 5s 场景）
- **CI nightly 无 key 跳过失效**：`exit 0` 只放行当前 step，后续 real_llm/评测 steps 无 key 时仍执行致 exit 2——改为 GITHUB_OUTPUT 条件门（workflow_dispatch 实测修复）

### 文档
- 飞书渲染支持矩阵（`docs/feishu_render_matrix.md`）+ 开发方法论（`docs/development_methodology.md`）

### 框架化批次（2026-08-15 追加）
- **headless 服务模式（B5）**：`examples/04_headless_service.py`（无 UI 纯 API 嵌入——`build_engine` 单实例 + 同步/流式对话端点约 20 行）
- **LLM 错误注入矩阵（A4）**：网络/超时/HTTP 4xx/HTTP 5xx/协议五类错误各注入引擎循环，断言 `[LLM 调用异常]` 三件套如实呈现 + 类型名不吞并 + 不抛穿
- **发布节奏制度化（B11）**：Release Drafter（PR 标题自动归类 changelog 草稿）+ tag 触发门禁复核 + Release 草稿生成 + CONTRIBUTING 发布流程
- **多 provider 成本路由增强（B6）**：`switch_model` 成功回执注入目标模型成本档 + 能力语义 + 上下文窗口（元数据缺失如实标注，判断归 AI）
- **插件化 Skill 可演示化（B3）**：仓库自带示例技能（`skills/`）入库，真实装配端到端测试
- **评测集贡献指南（B7）**：`docs/eval_scenarios.md`（schema + 判定注册 + 30 分钟新增路径 + PR 验收）
- **API 契约稳定化（B5）**：公共签名快照测试（build_engine/LoopEngine/SessionStore/ToolRegistry 参数锁定）+ api.md §1 装配链路可执行验证

## v0.3.0（2026-08-14）

### 新能力
- **插件化 Skill 加载**：`skills/<name>/SKILL.md` 目录自动扫描，AI 经 `skill_list`/`skill_load` 发现并加载外部技能执行（`SKILLS_DIR`，默认 `./skills`）——外部扩展零代码
- **动作状态条（H-UI）**：引擎动作观察者（thinking/tool_call/tool_result/answer/done 事件）+ 飞书状态卡实时更新（💭 思考中 / 🔧 正在调用工具 / ✅ 完成 / ✍️ 生成回答）；Web 流式本就支持（思考 + 工具进度链）
- **人工审批流**：EXEC_MODE 拦截项可在 CLI 交互模式终端确认（`set_approval_callback`，无终端 fail-closed 拒绝），审批审计落盘
- **symlink 写防护**：edit_file 写路径含符号链接拒绝（防越界写）；read_file 读 symlink 如实标注
- **评测体系**：固定评测集（6 场景）+ 运行器（`scripts/run_eval.py`，真实 LLM / `--dry`），Wilson CI 统计约束，CI nightly 自动运行
- **`LoopEngine.run_single`**：一次性便捷入口（自动建会话）

### 改进
- `LLM_MAX_ITERATIONS` 默认 20 → **40**（多步任务不再轻易触顶）；达 80% 注入 `[轮数预警]`，AI 可经 adjust_strategy 调大（硬上限 500）
- `HISTORY_MAX_CHARS` 默认收敛统一为 **100K**（1M 曾致上下文撑爆）
- 档案分片 + sidecar 检索索引（100MB 开新段，检索跨段最近优先，存量无索引全文扫描兜底）
- 飞书心跳历史轮转（`FEISHU_HEARTBEAT_HISTORY_MAX_MB`）
- HashEmbedder v2（2+3-gram）+ embedding 缓存版本化
- `model_catalog` 选型指引（成本/能力语义 + switch_model 引导）
- CI：GitHub Actions 三件套门禁（pytest/ruff/pyright）+ nightly 真实评测

### 文档
- 公共 API 参考（`docs/api.md`，含稳定 API 声明）+ 3 个示例（`examples/`）
- 配置参考（`docs/configuration.md`，分组配置表 + 常见坑速查）
- 事件溯源设计（`docs/event_sourcing.md`）+ 评测集扩展指南（`tests/eval_sets/README.md`）
- 英文 README（`README.en.md`）+ 贡献指南（`CONTRIBUTING.md`）

### 修复
- `maybe_trigger` 首次触发平台 bug（容器 monotonic 从 0 开始误判冷却，提取静默失效）
- pyright 1.1.411 兼容（divider 类型）、CI 环境兼容（测试自足）

## v0.2.0（2026-08-14）

- D1 事件溯源单一真相源（5 类事件 + 回放/对账/迁移/回滚/退役/会话 fork/过滤钩子）
- 实时停滞检测（连续同指纹 3 提醒 / 5 熔断）+ edit_file 换行归一化 + mtime 基线防并发
- 开源发布（Apache-2.0 + 公开面精简）
