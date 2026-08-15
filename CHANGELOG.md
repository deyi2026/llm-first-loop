# Changelog（公开变更记录）

> 面向使用者的变更摘要（内部开发过程记录不公开）。版本语义：0.x 内小版本可增补能力，不破坏既有行为。

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
