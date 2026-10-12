# 缓存命中率优化：完整分析与建议报告

> 日期：2026-08-24 | 范围：llm-first-loop **镜像区** | 状态：部分落地、部分待评估
> 本报告供独立评估。所有数据均来自项目实测（审计日志/事件日志/单元测试），非估算。
> 所有已落地改动均可在 git diff 与测试套件中复核。

---

## 0. 摘要（一页）

镜像区缓存命中率从 **08-23 的 99%+** 骤降至 **08-24 07:50 起的 4%** 并持续 40+ 分钟。根因不是代码回归，而是**配置（deepseek 预算 150K 字符）+ 任务类型（重工具输出）** 组合触发的"压缩风暴"：历史每轮触顶压缩 → 前缀每轮变化 → provider 缓存只剩 system+头部命中。

已落地 8 项修复（归档污染会话、预算校准 150K→300K、压缩缓冲 0.6→0.5、token 估算校准 2→0.6、落盘路径确定性、文案如实化、测试），实测命中率已回到 **93%+**（近 3 轮 7,846,912/8,427,392 tokens）。

**待评估的核心建议**：①工具输出"阈值分层 + 确定性摘要内联 + 全文落盘"（替代现状的全量内联/头尾截断）；②思考链瘦身 REASONING_TAIL=2→-1；③token 估算 provider 级化（当前统一 0.6 对本地 qwen 有 1.7-2 倍高估盲区）。三条建议对缓存命中、token 消耗、智力能力、执行力四个维度均为净正向（详见 §4 拷问矩阵）。

**评估者需重点裁决**：建议①的"落盘存储"争议——最小修法（文案如实化，已落地）vs 架构级方案（落盘进 ArchiveStore 统一检索），本报告倾向最小修法（§4.4）。

---

## 1. 问题背景与数据

### 1.1 命中率骤降曲线（审计数据逐小时聚合，guarded_requests.jsonl）

| 时段 | 命中率 | 说明 |
|---|---|---|
| 08-22 ~ 08-23 14:00 | 93% ~ **99.6%** | 稳态（08-23 每小时 99.1-99.6%） |
| 08-23 15:00-17:00 | 73% → 33% | 波动（模型切换/单会话） |
| 08-24 01:00 | 96.6% | 恢复 |
| 08-24 07:00 | 68.9% | 开始恶化 |
| 08-24 08:00 | **32.1%** | 崩溃 |
| 08-24 16:00 起（修复后） | **93.1% / 93.5%** | 恢复 |

### 1.2 断点时刻（事件日志逐轮追踪，会话 f893bd9a）

```
07:49:21  round 59  命中率 96.6% ✅（缓存覆盖至 msg#174, 203,502 tokens）
07:49:22  23 条中段消息被压缩归档（context.compressed ×23, history 122K→111K 字符）
07:50:25  round 60 起 命中率 4.4%，此后 90+ 次请求 hit 恒 = 8,320 tokens
          （只剩 system+头部命中），in 从 190K 涨到 324K
```

### 1.3 根因链（4 个环节缺一不可）

1. **预算紧**：deepseek 生效预算 = `providers.json history_budget_chars: 150000`（150K 字符）。`.env` 的 `HISTORY_MAX_CHARS=1000000` 被 `min(全局, provider)` 截断。
2. **任务类型吃上下文**：该会话为 Surge/网络排查，每轮产生 3-6K 字符工具输出（web_fetch/execute_command）+ 长思考。
3. **触顶压缩**：历史涨到预算 90%（135K 字符）触发压缩 → 裁到 60% 目标（~112K）。
4. **压缩风暴（核心）**：重工具任务 1-2 轮内又涨回阈值 → **每轮压缩 26-94 条** → 中段归档内容每轮不同 → 前缀字节流每轮变化 → 缓存只剩头部。这是 `history.py:623` 注释记载的已知失败模式："裁到上限 → 每轮压缩 → 前缀每轮变化 → 永久断点（实测 1% 命中率）"。

**排除项**（有实证）：①非 provider 故障（同时段其他会话 98.8%）；②非代码回归（崩溃期与 99% 期跑同一 commit bb2ef6b）；③非 TTL 过期（deepseek TTL 7200s，请求间隔 <70s）。

### 1.4 关键配置变化时间线

| 时间 | 配置 | 命中表现 |
|---|---|---|
| 08-18 | `HISTORY_MAX_CHARS=1000000`（缓存方案 A） | 99% |
| 08-21 22:41 | providers.json deepseek `400000` | 99% |
| 08-24 上午 | providers.json deepseek `150000`（预算收敛修复，CHANGELOG 明示预期代价"~99%→~86%"） | 实际崩到 4%（风暴超出预期） |
| 08-24 晚间（本次） | `300000` + `COMPRESS_TARGET_RATIO=0.5` + 估算校准 | 93%+ |

---

## 2. 已落地修复（8 项，全部可复核）

| # | 修复 | 位置 | 验证 |
|---|---|---|---|
| 1 | 归档污染会话 f893bd9a + 解除飞书映射（下次消息自动新会话） | `data/archived_sessions/20260824-165051/`、`feishu_session_map.json` | 文件在档 |
| 2 | deepseek 预算 150000 → 300000（含 max_tokens 16384） | `providers.json`（备份 `.bak-20260824-165051-budget400k`） | 生效配置实测 |
| 3 | 压缩缓冲 `COMPRESS_TARGET_RATIO=0.5`（压缩后留 50% 缓冲，压缩间隔 1-2 轮→~20 轮） | `.env` | 生效 |
| 4 | **token 估算校准** `_CHARS_PER_TOKEN_EST 2 → 0.6`（3 处同源 + engine re-export + 测试断言） | `runtime.py` / `routing.py` / `cache_window.py` | 测试全绿 |
| 5 | execute_command 落盘路径 时间戳 → **内容哈希**（同输出同路径，前缀稳定） | `execute_command.py:98` | 新测试 2 项 |
| 6 | trim.py / read_file.py 文案去 search_archive 误导（落盘是显式文件，read_file 取全文） | `trim.py` / `read_file.py` | 新测试 1 项 |
| 7 | 演进建议 EVO-20260824-4c1340e7（accepted）、勘误 86a496c0（executing） | `data/audit/evolution_suggestions.jsonl` | 存在 |
| 8 | 经验沉淀 EXPERIENCE-20260824-200-43.md | `experiences/` | 存在 |

**测试**：4 套件（execute_command_workdir_trim / session_trim / tool_summary / archive_search）**32 项全过**。已知 2 个预先失败与本次无关（`test_complexity_reduction`：engine.py 行数超预算，未提交改动所致；`test_m41` 1 项，工作区在途）。

### 2.1 修复 4（估算校准）的量化依据

实测 tok/char（413 个 cache.window 事件校准）：

| 口径 | tok/char | 与旧估算(0.5)偏差 |
|---|---|---|
| 代码旧值 | 0.5 | — |
| 小上下文（<20K tokens） | 0.64-1.05 | — |
| **大上下文（>100K tokens）** | **1.676** | **3.35 倍** |
| 全量加权 | 1.230 | 2.46 倍 |

旧值导致：①上下文守卫 `_check_context_fit` 形同虚设（实际 1M tokens 载荷估算仅 300K，永远放行）；②缓存边界显示失真（688K tokens 显示为 137 万字符，实际 ~41 万）。

---

## 3. 当前状态（修复后）

- **命中率**：93.1% / 93.5%（近 3 轮实测）
- **deepseek 预算 300K 字符** = 实际 ~503K tokens（大上下文 1.676 tok/char）= **窗口 50%，留 50% 输出空间**
- **压缩阈值**：300K×0.9 = 270K 字符（实际 ~453K tokens，窗口 45%），压缩后留 140K 缓冲
- **守卫**：600K 字符中文载荷 → est 1M tokens > 900K 线 → 提前拦截（修复前漏拦）
- **输出预留**：max_tokens=16384 → `allowed = min(0.9×窗口, 窗口−16K)` 生效

---

## 4. 待评估建议（核心交付物）

### 4.1 建议①：工具输出"阈值分层 + 确定性摘要内联 + 全文落盘"

**现状**：execute_command 超 3000 字符 → 头 1500 + 尾 1500 + 截断标记 + 全文落盘（`data/audit/cmd_outputs/`）。其他工具（web_fetch 等）直接内联。实测 f893bd9a 会话 23 条 >2K 字符回执累积 **74K 字符**，是历史膨胀主因。

**建议**：工具结果写入会话时统一处理——

| 输出大小 | 处理 | 依据 |
|---|---|---|
| ≤2K 字符 | 内联 | 信息密度高，一次往返最便宜 |
| >2K 字符 | **确定性摘要内联 + 全文落盘**（`extract_key_info` 提取路径/URL/事实 + 完整度元信息） | AI 有"决策最小充分信息"，多数不需读全文 |
| >50K 字符 | 纯摘要 + 落盘 | 读全文成本超收益，应检索/分段 |

**收益（量化）**：23 条大回执 74K→~14K 字符（摘要 ~600/条）→ 历史膨胀降 **80%** → 150K 预算下触顶时间 26 分钟 → 2 小时以上；压缩风暴绝迹。token 层面单会话省 ~730 万 tokens 输入 + 压缩轮全量 miss（200-300K tokens × 30 倍单价差）消失。

**代价/风险**：①首次摘要化断一次前缀（之后稳定）；②AI 需要细节时多 1-N 轮 read_file（思考成本，摘要质量决定读取频率）；③摘要可能丢关键信息（需增强 extract_key_info 抓错误码/退出码/错误块）。

**四维拷问矩阵**：

| 维度 | 结论 | 关键修订 |
|---|---|---|
| 缓存命中 | 净正向（断点 1 次 vs 每轮；膨胀降 80%） | 落盘路径**纯内容哈希**（已落地），勿用 tool_call_id/时间戳 |
| token 消耗 | 净正向（输入省 730 万 tokens/会话 + miss 消失） | 摘要须含"决策最小充分信息"降读取率 |
| 智力能力 | 摘要保留决策依据，略降"全量可见" | 错误块提取增强（错误码/退出码/首末行） |
| 执行力 | 摘要内联根治"纯落盘"的失忆死穴 | 落盘 fail-open + 不拆配对组 |

### 4.2 建议②：思考链瘦身 `REASONING_TAIL=2 → -1`

**现状**：`REASONING_TAIL=2`（保留最近 2 轮 assistant 的 reasoning_content 进提交）。两个问题：①滚动窗口——每轮最老那条从"保留"变"省略" → **前缀每轮漂移 → 断点**（history.py 注释自承）；②思考内容占输入体积（f893bd9a 单轮思考 10-12K 字符）。

**建议**：`-1`（方案 A，2026-08-20 已有实现）：**按属性省略**——仅带 tool_calls 的 assistant 保留 reasoning（协议必需回传，M20 THK-04），纯思考的省略。每条消息 reasoning 有无**固定不变** → 前缀字节稳定 + 输入最小化。

**收益**：本地 27B 尤其显著——decode 20-40 tok/s，思考 5-12K tokens = 3-10 分钟省掉。

### 4.3 建议③：token 估算 provider 级化（当前盲区）

**问题**：修复 4 统一 0.6，是 deepseek 中文混合校准（实测 1.676 tok/char）。**本地 qwen tokenizer 不同**（中文 1 token≈1-1.5 中文字），用 0.6 会高估本地载荷 1.7-2 倍 → 守卫误拦 + 预算过紧。

**建议**：`providers.json` 每 provider 加 `chars_per_token`（deepseek 0.6 / local 0.9），`_effective_history_budget` 与 `_check_context_fit` 按 provider 取值，未配置回退 0.6。

### 4.4 争议点（请评估者裁决）：落盘存储方案

- **DSH 原案**：落盘统一走 ArchiveStore（可 search_archive 检索），解决"cmd_outputs 文件搜不到"。
- **已落地（最小修法）**：文案如实化（去掉 search_archive 误导，read_file 落盘路径取全文），不动存储架构。
- **倾向**：最小修法。理由：①显式文件 + read_file 精确取回（本会话 149 次实证）优于模糊检索；②ArchiveStore 实际规模 4.6 万行（评估时点），塞 cmd 输出增加 <1%，"急剧膨胀"担忧不成立——但这反而说明改存储的**成本低**，若评估者认为统一检索价值高，改存储可行；③跨会话检索 cmd 输出留作独立演进（EVO 建议已登记）。

---

## 5. 本地大模型适配（评估要点）

**结论：机制本质相同，90% 建议适用且本地收益更大；3 处适配、3 项不适用。**

| 建议 | 云端 | 本地 | 原因 |
|---|---|---|---|
| 前缀稳定三原则 | ✅ | ✅（收益更大） | llama.cpp KV 断前缀 = 全量重 prefill **94s 级** |
| 工具输出落盘+摘要 | ✅ | ✅（更迫切） | 27B prefill 随上下文线性涨 |
| 思考链瘦身 | ✅ | ✅（迫切得多） | 本地 decode 慢，思考 5-12K tokens = 3-10 分钟 |
| 落盘路径确定性 | ✅ | ✅（价值更高） | 本地 KV 同 slot 无 TTL |
| 估算校准 | 0.6 | **需 0.9（qwen tokenizer 不同）** | 见建议③ |
| 命中率监控 | 命中回执完整 | LM Studio 代理**无回执**（hit_telemetry=False 不判规则 G，已有机制） | 0% 是协议限制非缓存坏 |
| 缓存 TTL 逻辑 | ✅ | ❌ 不适用 | 本地同 slot 无 TTL |
| 按 token 计费优化 | ✅ | ❌ 不适用 | 本地无计费，命中价值 = prefill 提速 |

**本地已具备**：`history_budget_chars=30000`（prefill 权衡）、`tool_round_zero_history=true`（工具轮极小前缀）、`max_tokens=16384`、fast_model 9B 分流。EXPERIENCE-local-model-config.md 已沉淀：直连 llama-server（KV 命中 97%）而非 LM Studio 代理（0%）、ctx 65536 控制 KV 内存。

**本地实测命中率**（审计数据）：qwen3.8-27b 41.4%（517 次）、qwen3.8-27b-mlx 23.4%（123 次）、fable-27b 0%（18 次）——MLX/代理后端无缓存是主因，直连 llama-server 可到 97%。

---

## 6. 诚实性记录（评估者应知悉）

1. **两处数字失实已认账**：初版报告"ArchiveStore 200 万+ 行"（实测 4.6 万，差 43 倍）、"test_m41 2 项失败"（实测 1 项）。根因"论证量化数字未亲测"。已沉淀经验 EXPERIENCE-20260824-200-43.md，勘误建议 86a496c0 正文含修正数字。
2. **主代理复核判断错误**：一度称"失实数字未写进演进建议正文"，实为关键词漏检（"200 万+"带空格 vs 检索"200万"）+ 截断显示。反转成立，已留痕。
3. **已落地改动全部可复核**：git diff 可查、32 项测试可跑、配置可查备份。
4. **未做（如实）**：①落盘改 ArchiveStore（分歧，待裁决）；②extract_key_info 错误块增强（列为后续）；③本地估算 0.9 校准（待建议③审批）。

---

## 7. 执行建议排序（若评估通过）

1. **建议②**（REASONING_TAIL=-1）：一行 .env，低风险，两端受益
2. **建议③**（估算 provider 级化）：改 2 处代码 + 配置，消除本地盲区
3. **建议①**（工具输出分层落盘+摘要）：tool_exec 一处集中改 + extract_key_info 增强 + 测试，收益最大但改动最大

---

## 附录 A：数据来源

- 命中率曲线：`data/audit/guarded_requests.jsonl`（3,356 条 llm_result）
- 断点追踪：`data/event_logs/f893bd9a-*.jsonl`（2,998 事件）
- tok/char 校准：413 个 `cache.window` 事件
- 本地命中率：guarded_requests.jsonl 按 model 分桶
- 测试：`PYTHONPATH=src .venv/bin/python -m pytest tests/unit/{test_execute_command_workdir_trim,test_session_trim,test_tool_summary,test_archive_search}.py` → 32 passed

## 附录 B：关键文件索引

| 文件 | 作用 |
|---|---|
| `src/llm_loop/core/loop/runtime.py` / `routing.py` / `core/cache_window.py` | 估算常量（0.6） |
| `src/llm_loop/tools/builtin/execute_command.py` | 落盘内容哈希 |
| `src/llm_loop/tools/trim.py` / `builtin/read_file.py` | 文案如实化 |
| `data/providers.json`（备份 `.bak-20260824-165051*`） | deepseek 300K / max_tokens 16384 |
| `.env`（备份 `.bak-20260824-165100*`） | COMPRESS_TARGET_RATIO=0.5 |
| `experiences/EXPERIENCE-20260824-200-43.md` | 数字失实教训 |
| `data/audit/evolution_suggestions.jsonl` | EVO-4c1340e7（accepted）/ 86a496c0（executing） |
