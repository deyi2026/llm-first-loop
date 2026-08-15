# Changelog（公开变更记录）

> 面向使用者的变更摘要（内部开发过程记录不公开）。版本语义：0.x 内小版本可增补能力，不破坏既有行为。

## v0.6.6（2026-08-15）

### 修复：tool_call.arguments 归一化回归（v0.6.5 引入，工具通道断连根因）
- 根因：v0.6.5 客户端重写时本地重定义了 ToolCallDeltaAggregator（原版从 llm/schemas.py 导入），
  新实现 finish() 不解析 arguments → 真实 provider 的 JSON 字符串 arguments 原样进注册表 →
  所有工具调用被 "[参数错误] 参数必须为 JSON 对象" 拒绝（FakeLLM 预构造 dict 的测试盲区）
- 修复：复用 schemas.py 聚合器（finish 含 json.loads 归一 + _raw_arguments 兜底）；
  Anthropic tool_use start 空 input 不并入（防 "{}" 破坏 JSON）；Google functionCall 独立 index
- 回归防护 +4（归一/非法兜底/端到端真实客户端 mock SSE→read_file 真实执行/注册表防线）
- 门禁 pytest 2090 + ruff 0 + pyright 0

## v0.6.5（2026-08-15）

### P3-5：provider 广度——Anthropic / Google 原生协议（wire_protocol）
- LLMClient 协议分发：`openai`（默认零回归）/ `anthropic`（Messages API：/v1/messages + x-api-key +
  anthropic-version，system 拆分、tool_use/tool_result 转换、thinking_delta/input_json_delta 流式解析）/
  `google`（Gemini：streamGenerateContent?alt=sse + x-goog-api-key，contents/systemInstruction/
  functionDeclarations，functionCall 聚合、MAX_TOKENS→truncated）
- 元数据驱动：ModelSpec.wire_protocol（providers.json 模型条目，非法值回退 openai 如实告警）；
  client_params/pool/factory 全链透传；LLM_WIRE_PROTOCOL 可配默认 client
- 修复：Python 3.11+ 裸 yield-from 丢弃子生成器返回值（终态 LLMResponse 必须显式捕获 return）
- 测试 +7（anthropic payload/头/tool_use 聚合、google payload/functionCall/截断、默认零回归、
  provider 解析/非法回退）；门禁 pytest 2084 + ruff 0 + pyright 0

## v0.6.4（2026-08-15）

### P3-4：workflow_run DAG 编排（拓扑序 + 节点级预算，无 graph DSL）
- `mode=dag`：步骤可声明 `id` + `depends_on`（id 或 0 起下标）依赖；Kahn 拓扑排序确定执行序，
  依赖步骤 final_answer 自动注入被依赖步骤 context（【依赖步骤 X 结果】标注）
- 校验诚实：未知依赖/自依赖/重复 id → 400 式如实失败；**循环依赖 → 拓扑前检测**（不派发任何步骤）
- **节点级预算** `budget_rounds`：透传子代理 max_rounds（SubAgentRunner.run 新增可选参数，
  提示文案与循环守卫同步生效）；回执如实标注 budget
- parallel/pipeline 同步支持 budget_rounds（通用节点预算）
- 测试 +6（拓扑序+依赖注入/环检测/未知依赖/自依赖/重复 id/预算透传）；门禁 pytest 2079 + ruff 0 + pyright 0

## v0.6.3（2026-08-15）

### P3-2：英文文档对等化
- `README.en.md` 整体重写为与中文版对等（157 行，章节/功能 27 条/配置表/CLI 命令逐条对应；程序输出标记保留中文原样，与源码字面一致）
- 新增 `docs/api.en.md`（142 行，章节数与中文版一致 19 段）与 `docs/ai_rules.en.md`（217 行，RULE-AI-00~11 全部编号对等）
- `docs/INDEX.md` 链接补充；英文文档对等守护测试 +3（api 章节数/规则编号/README 版本一致）

## v0.6.2（2026-08-15）

### P3-3：bash 沙箱后端（EXEC_SANDBOX=bwrap|none，可选）
- `EXEC_SANDBOX=bwrap`：bubblewrap 隔离 execute_command——只读系统目录（/usr /etc /lib /lib64 /bin /sbin）、
  /dev /proc 挂载、/tmp 临时文件系统、工作区可写绑定、独立 PID/UTS/IPC 命名空间
- **fail-closed 语义**：显式开启而 bwrap 缺失 → 命令不执行、回执如实说明（不静默降级）；
  回执标注"已启用 bwrap 沙箱"
- 前台/后台（run_in_background）双路径接线；未启用零回归（shell=True 路径不变）
- 测试 +8（argv 结构/禁用/启用/缺失 fail-closed/回执标注/后台/零回归）；门禁 pytest 全绿

## v0.6.1（2026-08-15）

### P3-1：MCP 客户端接入（stdio）
- `MCP_SERVERS` env JSON 配置 stdio MCP 服务器；启动连接握手（initialize/initialized/tools/list）
- 工具以 `mcp.<server>.<tool>` 名注册（inputSchema 透传为 parameters），执行走统一注册表通道
  （线程超时 / 输出分层 / 审计复用）；结果五态包装（success/failure/blocked/timeout/error）
- 诚实边界：单服务器连接失败 fail-open（其余服务器/工具不受影响）；调用失联单次重连，
  仍失败 → ERROR 态如实；isError → FAILURE 态（content 原样透传）
- 测试 +10（配置解析/真实 stdio 握手与清单/schema 透传/五态/注册表集成/双服务器 fail-open）
- 门禁：pytest 2062 passed + ruff 0 + pyright 0

## v0.6.0（2026-08-15）

### 修复：飞书收到回复后多一条重复 [跨端同步] 消息（P1-11 竞态）
- **根因**：`CrossSyncWatcher`（飞书←Web 增量同步）的基线刷新（`mark_processed`）原在**回复发送后**才调用——回答落盘与基线刷新之间存在秒级窗口，轮询（1.5s）会插入其中，把桥自己的回答当"Web 侧增量"重复推送一条 `[跨端同步]`（用户反馈重复）
- **修复**：① `mark_processed` 前移到 `engine.run` 返回后立即执行（窗口缩至微秒级）；② `cross_sync` 新增 `busy_fn`——桥正在处理消息时整轮暂停轮询（busy 清除后增量按累积 diff 一起推，不丢消息）；两保险彻底消除重复
- 飞书测试 191 全绿（含 busy_fn 语义用例）

### 窗口锚定：历史起点固定 → 前缀缓存全量命中（P1-10）
- **根因**：预算裁剪"从最新往回保留"导致每次提交的保留集合**起点移动**（旧的挤出、新的加入）→ system+历史前缀每次从历史第一条就变 → llama.cpp/服务端前缀缓存几乎全 miss（冷 prefill 每轮 ~20-56s）
- **锚定机制**：按 provider 在会话持久化窗口锚点（`history_anchors`）——锚定后起点固定（只追加不挤旧）；超预算依次：①剔除注入消息（不进提交、零损失、不产生归档）②分层降级中段旧 tool ③仍超才归档推进锚点（前缀断一次后重新锚定，低频）
- **实测（真实大会话 + local 9B）**：前缀一致率 **48/49（98%）**；连续 run 首分片从 20-56s → **3.8-11.5s（缓存命中）**
- 快照注入仅无锚时执行（锚定后快照为推送式注入已打标跳过提交，避免锚点换算复杂化）；无锚路径行为零变化

### 云端 provider 提速降本：前缀稳定 + 历史预算（P1-9）
- 本地模型优化（P1-7 前缀稳定 / 历史预算）推广到云端：deepseek/kimi 配 `history_budget_chars: 60000` + `inject_system_notices: false`、minimax 配 `40000` + false——system 前缀静态化命中服务端 prompt 缓存（输入 token 折扣）+ 控制输入量（成本），推送式注入仍可经 architecture_status 自查（能力零损失）；超时保持全局 120s 不放大（provider 级差异由配置天然表达）
- 实测：kimi/k3-256k 默认模型端到端正常（in=5916 tokens, 回答正确）

### 默认模型支持全限定 `provider/model`（P1-8）
- `LLM_MODEL=kimi/k3-256k` 形式全限定默认模型 → 默认 client 按注册表 provider 参数装配（base_url/api_key 来自 provider 配置、模型名发送裸名，OpenAI 兼容端点不接受全限定）；裸模型名保持 env 三件套（零回归）
- 配置：`.env` 默认模型已切至 `kimi/k3-256k`（备份 `.env.bak-20260816-kimi`）

### 本地模型首 token 提速：推送式 system 注入不进提交视图（P1-7 前缀稳定）
- **根因（Stateful API 可行性验证）**：LM Studio Stateful API 增量续聊实测 TTFT 0.58s，但 OpenAI 兼容端点在**相同前缀**下同样命中引擎 KV 缓存（2.9s）——让 agent 缓存失效的真正元凶是**每轮注入的 system 消息**（[架构上报]/[预算预警]/[声明提醒]/快照，大会话已累积 181 条），下次 run 全部合并进开头 system → 前缀从第一个 token 就变 → 每轮全量冷 prefill
- **provider 级开关 `inject_system_notices`**：默认 True（零回归）；`local` 配 false → 推送式注入（架构上报/预算预警/轮数预警/声明提醒/快照/自我评估提醒）仅落会话、不进提交视图（AI 可经 architecture_status 自查，能力零损失）；功能性注入（压缩标注/降级通知/overflow 回注/轮次决策请求/故障反馈）不受影响
- **存量消息兼容**：跳过判定 = metadata 标记 + 内容前缀（[架构上报] 等）双通道，历史遗留注入消息同样生效
- **实测**：system 前缀稳定为静态文本（+压缩标注尾部），首分片从 ~70s 降至 ~25s（9B 冷 prefill 固有成本；多引擎 CPU 争抢缓解后更低）

### Web V2：全新 React 端（对齐 DeepSeek Harness Web，双版本并存）
- **独立目录 `webui/`（React 18 + TS + Vite）**，挂载 `/ui/v2` 与原版 `/` 并存（原版保留可回退）；独立分支 `feature/web-v2` 合入
- **视觉对齐**：DSH 同源设计 token（亮/暗/跟随系统，`--dsw-alias-*` 语义变量 + shiki 代码配色）、三栏布局壳、消息入场动效、移动端抽屉
- **功能对齐**：流式会话（思考块/工具链状态chip/代码块分块）、`/` 命令面板（点选即执行）、模型目录、消息反馈（👍👎 → feedback.jsonl）、会话 Markdown 导出、子代理标签、跨端同步（SSE 命名事件 + 失联自愈看门狗）
- 侧栏管理：置顶/两步确认删除/分支（fork→自动切换）/来源通道标签
- 识别链路（后端增强，原版/飞书同受益）：**auto 链**——团队识别工具（arkcli）优先 → 注册表 multimodal 模型（Kimi 实测可用）兜底 → 明确报错；docx/pdf 走 doc-extract 结构化抽取（本地提取兜底）；识别失败附件如实标注"图片未包含"防幻觉
- 新端点：`POST /api/v1/sessions/{id}/feedback`
- 文档：`docs/web-v2-diff.md`（DSH 对齐三态清单/差异对比/切换方案）

门禁：pytest 2038 passed + ruff 0 + pyright 0 + Vitest 29/29 + 分支 CI 全绿

## v0.5.6（2026-08-15）

### 修复：飞书发消息 Web 端必须手动刷新才显示（SSE 命名事件缺失）
- **根因**：SSE 规范中命名事件必须带 `event: <type>` 行；服务端只发 `data: {"type": ...}` → 浏览器按默认 `message` 事件处理，前端 `addEventListener("sessions_updated")` 永不触发（curl 能看到数据流，浏览器里却没有任何回调）
- **修复**：事件帧补 `event: connected` / `event: sessions_updated` 命名行（data 内 type 字段保留向后兼容）；新增 20s keepalive 注释行防长连接被中间层/浏览器超时掐断
- **前端加固**：失联自愈看门狗（>25s 无事件且页面可见 → 静默自愈刷新，SSE 健康时不触发）；标签页重新聚焦立即同步（后台标签页 SSE/定时器被浏览器节流时兜底）
- 测试 +6（命名帧格式 / 端点防回退守护 / 前端看门狗·聚焦·监听器静态守护）；全量 2020 passed + ruff 0 + pyright 0

## v0.5.5（2026-08-15）

### 双端统一会话 + 双向实时同步（用户需求）
- **统一会话**（已有机制确认）：owner 飞书私聊与 Web 共享同一会话（`shared_current`），Web 默认加载跨端共享当前会话；Web 新建会话同样设为共享当前
- **Web ← 飞书**（已有）：SSE `/api/v1/events` 指纹轮询，飞书侧新消息 Web 端 1.5s 内自动刷新
- **飞书 ← Web（新增）**：桥进程内 `CrossSyncWatcher` 后台线程——轮询会话目录，对映射到飞书聊天的会话（含 owner 共享当前）做增量检测，Web 侧用户输入/AI 输出**实时推送到飞书聊天**（卡片：`[跨端同步] Web 端会话「标题」新增 N 条消息`，角色标注 + 截断）
- 基线机制：桥自身回复完成后 `mark_processed` 刷新基线（不重复推送自己）；首见会话只建基线不推历史；速率受限（3s 最小间隔）多条合并；推送失败不推进基线（下轮重试，fail-open）
- `FEISHU_CROSS_SYNC=0` 关闭；测试 7 项（增量推送/自身不重推/Web 先建会话推 owner/限速合并/清理不推/损坏 fail-open/键解析）

## v0.5.4（2026-08-15）

### 显式输出预算 max_tokens（现场修复：长分析被截断、思考占大半输出只余少数）
- **根因**：请求未携带 max_tokens → 走模型默认（如 4096）；思考链模型思考占预算大半，最终分析被截断（现场：回答末尾直接中断在"（回答被截断）"，确认项都未列完）
- **修复**：`LLM_MAX_TOKENS` 默认 **8192**（env 可调）显式下发；`data/providers.json` provider 条目支持 `"max_tokens"` 覆盖（local/minimax 已设 16384）；pool 继承链路（provider 优先 → 默认 client）与客户端 payload 全链路接通
- 测试：payload 携带/缺省/配置默认/factory 装配/provider 解析与回退（+11 项）；FakeLLM 桩对齐新字段
- 配置文档补 `LLM_MAX_TOKENS` 行

## v0.5.3（2026-08-15）

### 消息响应提速：事件日志 O(n²) 续号修复（agent 通用路径，本地/云端同受益）
- **根因（用户反馈"发消息 1 分钟模型才有反应"）**：大会话（如 654 条）压缩归档时对每条消息单独写一条事件日志，而 `EventStore.append` 为求最大 seq **每次全文件扫描**——625 次连续 append 总耗时 O(n²)，实测 62s 阻塞在主循环（LLM 调用之前）；云端 80K 预算归档同样多，故本地/云端一样慢
- **修复**：seq 续号改**尾部读取**（append-only 文件最大 seq 必在尾部，反向读最后一条事件，O(1)；含损坏行容错与多段归档段取大）；`last_seq()` 同口径；`_resolve_msg_seq` 优先用 run 中内存会话（P0-5 绑定表），避免每次归档都读盘
- **实测（真实 654 消息会话 + 9B）**：run 97s → 37s，其中 LLM 固有 prefill+生成 35.7s（cProfile 实证），**agent 管线 63s → 1.3s**
- 事件日志语义零变化（seq 单调、损坏行容错、flock 并发安全、滚动兼容），相关测试全绿


### 本地大模型接入：provider 级超时（修复 LLM 请求超时 120s）
- **根因**：本地大模型（LM Studio 27B 量化实测 ~5s/千字 prefill）在 120s 全局超时内完不成首 token——40K 字上下文实测 208s 才出首字节，大上下文会话（几十万字符）必然超时报 `LLMTimeoutError: LLM 请求超时（120.0s）`
- **provider 级 `timeout_s`**：`data/providers.json` 每个 provider 可配 `"timeout_s": 600`（本地慢模型放大，云端保持全局默认零回归）；`model_catalog` 目录标注 provider 超时
- **调用语义修正**：`timeout_s` 未被 `adjust_strategy` 显式调整时，循环不再下发 per-call 覆盖，让 client 自身超时（provider 级优先、全局兜底）生效——此前 provider 配再大也会被循环的 120s 覆盖
- **配置**：`data/providers.json` 的 `local` 已配 `"timeout_s": 600`；`docs/configuration.md` 常见坑新增本地模型超时排查三步（调超时/控上下文/换轻模型）

### 本地大模型接入：provider 级历史预算（agent 发给本地模型的上下文过长问题）
- **根因（用户指出）**：agent 每轮发给本地模型的历史按全局 `HISTORY_MAX_CHARS`（80K 字符 ≈ 56K tokens）构建，本地模型 prefill 随上下文线性涨——80K 字符在 CPU 级 27B 上首 token 要 7-10 分钟，即使窗口装得下也慢得不可用；实际有用的近期内容远小于全量历史
- **provider 级 `history_budget_chars`**：`data/providers.json` 每个 provider 可配历史注入预算（字符），`_effective_history_budget` 取 min(全局, 窗口折算, provider 预算)——`local` 已配 `"history_budget_chars": 12000`（≈9K tokens），实测真实会话发送载荷 69,697 → 13,510 字符（5 倍缩小），27B 首 token 缩到 1-2 分钟、9B 10-20 秒；旧历史照常压缩归档可检索（信息零丢失，RULE-AI-00 不变）
- **`[预算预警]`/context_usage 占用率口径修正**：改为统计**实际发送载荷**（构建后消息），不再把已压缩归档的原始会话算进"当前占用"——旧口径在收紧预算后会虚高数十倍（实测 440K vs 实际 70K），误导 AI 压缩决策；`architecture_status.context_usage.breakdown` 同步如实
- **配置**：`data/providers.json` 的 `local` 已配 `"history_budget_chars": 12000`；云端 provider 不配则完全零回归

## v0.5.3（2026-08-15）

### 现场修复：代理假 IP 段（198.18/15）误拦 web_fetch（本地大模型接入用户现场）
- **背景**：Surge/Clash fake-ip 模式下代理 DNS 把目标域名解析为 198.18.0.0/15 假地址；Python `is_private` 将该段判为私网 → SSRF 防护误杀代理环境下全部外网抓取（`[内网拦截] 目标地址属于私网/保留地址段（198.18.x.x）`），既有测试被迫 `WEB_FETCH_BLOCK_PRIVATE=0` 绕过
- **修复**：全部解析地址落在 198.18/15（代理假 IP）→ 默认放行 + 回执如实标注「已按代理通道放行」；`WEB_FETCH_BLOCK_FAKE_IP=1` 恢复严格拦截；真实私网/回环/链路本地/保留段拦截语义不变（P0 不回归）；连接后对端复核（TUN 假 IP）同步放行
- **测试**：新增 `test_web_fetch_fake_ip.py`（8 项）；撤销 m48/paging/builtin 中 17 处"关拦截"绕过（修复后拦截开启下通过）
- **对端复核容错**：透明代理转发（Surge pf 重定向，对端为本机回环）放行 + logger 留痕——per-hop 预检查已把关目标，真实私网对端仍丢弃（P0-3 主体不变）；端到端实测 `example.com` 经代理通道抓取成功且回执如实标注

## v0.5.2（2026-08-15）

### 回复展示：不折叠，过长分块输出（用户需求批次）
- **Web**：回复正文折叠整体移除（消息体级 2000 字摘要折叠 + 「展开全文」按钮删除）；超长代码块（>200 行）由折叠摘要改为**顺序分段全量展示**（每段 ≤200 行、段首标注「第 i/N 段 · 共 X 行（自动分块，未折叠）」、逐段语法高亮与复制按钮保留）
- **飞书**：长回复默认**不折叠全量分段推送**（markdown 感知分段既有能力）；`FEISHU_FOLD_LONG_REPLY=1` 选择加入旧折叠行为（摘要卡 + 「展开全文」取回，命令保留向后兼容）
- 折叠实现（collapseUnit/折叠样式类）整体移除，防复活守护测试改写

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
