# REPORT-20261014: .env 配置生命周期盘点与收口

- Goal: GOAL-20261014-46b9600a ｜ Task: TASK-46b9600a-001
- 日期: 2026-10-14 ｜ 执行: LFL
- 范围: 仓库根 `.env`（活配置）。`.releases/*/​.env` 为历史发布快照，不在范围。
- 方法: 三遍机械扫描（生效行解析 → 全库读取点 → 代码默认值解析）+ 定向人工核验，逐项过三问（用途 / 验证计划 / 回收条件）。
- 结论: **96 项生效赋值 → 删除 10 项死配置（11 行）+ 修正 1 处误导性注释 → 保留 86 项**；其中 3 项挂「需用户确认」、2 项挂「后续待办」。

## 1 证据链

| 证据 | 位置 / 引用 |
|---|---|
| 盘点前 .env 快照（279 行, sha256=a9123636…7036） | `artifact://v1/c62d301a6a774cf4990e40828945d154` |
| 三遍扫描结构化结果 | `data/tmp_inventory/env_inventory.json` / `_v2.json` / `_v3.json` |
| 读取点+默认值扫描回执（96 项分类） | evidence://v1/44c7897c42ad8d08e6a835e3ac5b86d10853f7235f4fa4060a574b1b98c00a72 |
| 死候选定向核验回执（SELF_EVAL/FEISHU_WS/EXPERIENCES_DIR/EVIDENCE_MODE/interop 读取点等） | evidence://v1/2076d9350b07a6dccb5bafb047fdf22dfd481fa900a3eadf5cdae92bd45757e3 |
| interop 流量盘点 + EVOLVE_LOCAL_EXEC 溯源回执 | evidence://v1/5f7f4d8d790b21c0c3bd9f21168ea27e7ee703e4393ebdf2d87778344b90123d |
| 删除动作回执 | §4 + 备份 `.env.bak-20261014-133458-inventory`（18710 字节 = 原文件；post sha256=7ed306375272df4bdad3df205ef9a1b32237c1ceb833af899683ea058104ffb9） |
| .env 未入 git（含密钥） | `git log -S <var> -- .env` 九个候选全部零历史；行内注释即历史档案 |

扫描方法学备注：多数默认值经多参 helper（`env_one(_env_x, "NAME")` / `business_config_snapshot` 动态 `.get("NAME")` / resolver 元组表）读取，单行正则会漏报——死配置判定一律以**宽松字面量全库 grep 零命中**为准，不以严格调用正则为准。

## 2 删除清单（死配置 10 项 / 11 行）

统一判据：全库（src/tools/scripts，含多行调用与动态查找形式）零消费；providers.json 无 `api_key_env` 引用；删除 = 回代码默认，行为零变化。

| # | 变量 | 前值 | 零读取证据 | 三问收口 |
|---|---|---|---|---|
| 1 | `KIMI_API_KEY` | sk-kimi-EY…UU4G（掩码，全值在备份） | providers.json 无 kimi provider；仅 cache_guard 敏感名单（掩码用途，非消费）+ 测试 | 用途：无消费方。回收：删除；恢复=kimi provider 接入时重录 |
| 2 | `TOOL_TAIL` | `0` | src/tools/scripts 零命中 | 2026-08-19 实验遗留；功能已不在代码面。回收：删除 |
| 3 | `SELFHEAL_ENABLED` | `1` | 零命中（`SELFHEAL_MAX_ATTEMPTS/MAX_PER_ROUND` 在 config.py:1108-1109 仍读，仅 enabled 旗标无读取方） | 功能旗标被移除后残留。回收：删除 |
| 4 | `SELF_EVAL_REMIND_ENABLED` | `1` | 零命中；现配置面仅 ENABLED/MIN_SAMPLES/SPAN（config.py:1115-1117） | 提醒机制折叠进 SELF_EVAL_ENABLED 后残留。回收：删除 |
| 5 | `SELF_EVAL_INTERVAL_ROUNDS` | `50` | 同上零命中 | 同上。回收：删除 |
| 6 | `INBOX_WAKEUP` | `1`（含 2 行注释） | 唯一读取点 interop_watch.py:39，仅对 **topic=coordinate** 触发（job/notify 永不触发）；机械盘点 interop 历史消息 **1433 条全部 notify，coordinate=0**——存续 8 周期间可触发条件从未出现，实际零行为 | 实证反例收口：删除=回默认 0，行为零变化。恢复条件：interop coordinate 协作协议启用时重开（一行） |
| 7 | `LMS_API_KEY` | 1R8i-lKbU…tk7qs（掩码） | 全库零命中；providers.json 无对应 | 用途不明且无消费方。回收：删除；全值在备份 |
| 8 | `COGNILOCAL_API_KEY` | `sk-local-noauth` | 全库零命中；providers.json cognilocal 条目 `api_key_env=""`（=免认证，providers.py:358-369 只认显式 `api_key_env`，无 f-string 回退）；本地模型 2026-10-14 已裁决弃用 | 本地模型栈残留。回收：删除 |
| 9 | `MXNOOK_API_KEY` | e19e2aab…f62a（掩码） | 全库零命中；providers.json 无 mxnook（GLM 中转已被 bigmodel 直连 key 取代） | 2026-08-30 中转接入遗留。回收：删除；全值在备份 |
| 10 | `LFL_DUPLICATE_GUARD_MODE` | `shadow` | 宽松 grep `duplicate_guard` 全库零命中 | R8.7 实验旗标，特性已不在代码面。回收：删除 |

注释修正（1 处）：`METHOD_REFLECTION_MODE` 行注释原称「回退：删此行即回 off」——代码默认已改为 auto（config.py:318-322，`_env_method_reflection_mode` unset→"auto"），按旧注释删行会得到 auto 而非 off。已改为：「回退：删此行=回代码默认 auto（2026-10-14 盘点核验…；off 需显式置 off）」。

## 3 保留项——非默认配置生命周期表（≠DEF，逐项三问）

读取点行号为本次核验事实（src/llm_loop/…）。

### 3.1 模型接入与降级
| 变量=值 | 代码默认(读取点) | 用途/依据 | 验证 | 回收条件 |
|---|---|---|---|---|
| `LLM_MODEL=glm/glm-5.3-flash` | ""(config.py:812) | 2026-10-14 用户裁决：默认 GLM | 每日调用回执在证 | provider 退场时随裁决更新 |
| `MODEL_FALLBACKS=glm/glm-5.3-flash,minimax/MiniMax-M3` | ""(config.py:1126) | 2026-10-14 裁决移除 deepseek 档 | architecture_status.model_fallback 可观测 | 降级链结构调整时更新 |
| `LLM_REASONING_EFFORT=max` | "high"(config.py:617,975) | 2026-09-20 用户决策 A | 调用回执在证 | 决策型，随模型栈变更复审 |
| `LEARNING_MODEL=glm/glm-5.3-flash` | ""(config.py:1067) | 2026-09-23 用户裁决：学习通道隔离 | 提取/反思走 flash 的运行记录 | 同上 |

### 3.2 上下文/工具行为
| 变量=值 | 代码默认(读取点) | 用途/依据 | 验证 | 回收条件 |
|---|---|---|---|---|
| `HISTORY_MAX_CHARS=1000000` | ""(manifest.py:254 等) | 2026-08-18 缓存方案 A | 长会话不压缩的运行事实 | 缓存策略变更时复审 |
| `REASONING_TAIL=-1` | 0(config.py:1100) | M66 按属性省略，前缀缓存安全（实验14 100%命中） | 实验回执在案 | 同上 |
| `TOOL_MAX_OUTPUT_CHARS=30000` | 100000(config.py:1003) | 输出截断收紧 | — | 与 working-set 参数联调时复审 |
| `TOOL_PIPELINE_ENABLED=1` | false(config.py:1035) | EVO-20260813 工具瀑布 | 启用后长期无回归记录 | 转正候选：可提演进改默认 1 后删行 |
| `TOOL_MATERIALIZE_ENABLED=1` | false(config.py:1036) | 同上（物化） | 同上 | 同上 |
| `MEMORY_TOP_K=5` | 未设→自适应(config.py:839-841) | **语义非默认**：显式设值关闭 memory_top_k 自适应通道 | — | 若恢复自适应则删行 |
| `LFL_TOOL_WORKING_SET_RECEIPTS=1` | false(config.py:899) | 2026-09-08 convergence canary（机械折叠） | canary 注释在案 | canary 转正/移除时随裁决 |
| `LFL_TOOL_WORKING_SET_BATCH_CHARS=65536` | 32768(config.py:901) | 同上（批量 64K） | 同上 | 同上 |
| `LFL_TOOL_WORKING_SET_GRACE_GROUPS=1` | 0(config.py:904) | 同上（宽限组） | 同上 | 同上 |
| `LFL_EXACT_DUPLICATE_TOOL_FOLD=1` | false(config.py:1037) | 同族 canary（≥3 精确重复组折叠） | 同上 | 同上 |
| `PRECHECK_ENABLED=1` | false(config.py:1098) | EVO-20260822 参数预检 | 长期启用无回归 | 转正候选 |

### 3.3 记忆/检索
| 变量=值 | 代码默认(读取点) | 用途/依据 | 验证 | 回收条件 |
|---|---|---|---|---|
| `EMBEDDING_PROVIDER=api` + `EMBEDDING_BASE_URL=127.0.0.1:8765/v1` + `EMBEDDING_MODEL=bge` | none/""/""(config.py:1083-1085) | 本地 bge 语义服务 | **端口 8765 OPEN（本次实测）** | 服务下线时随撤 |
| `EXTRACT_MAX_INPUT_CHARS=30000` | 100000(config.py:1102) | 提取输入收紧 | — | 与提取质量复盘联动 |
| `SEMANTIC_MEMORY_ENABLED=1` | false(config.py:1088) | 语义记忆域开 | search_evidence 在证 | 分域策略变更时 |
| `SEMANTIC_EXPERIENCE_ENABLED=1` | false(config.py:1092) | 语义经验域开 | 同上 | 同上 |

### 3.4 演进/证据/知识
| 变量=值 | 代码默认(读取点) | 用途/依据 | 验证 | 回收条件 |
|---|---|---|---|---|
| `EVOLVE_LOCAL_EXEC=2` | 0(config.py:596,263-272) | **非默认+安全相关**（2=全面执行档）；本仓库未检索到显式决策记录 | ⚠ 列入 §5 待确认 | 待用户裁决：维持/降级/补决策记录 |
| `EVIDENCE_MODE=enforce` | "off"(config.py:992) | ERC rollout（2026-08-27 canary R12 解除+R7-V2 PASS） | 工具回执强制证据链运转中 | rollout 完成转正或回 shadow |
| `LFL_KNOWLEDGE_ADVISOR=shadow` | "off"(config.py:948) | 知识顾问受控试点 | shadow 只记录不拒绝 | 试点结论落地时 |
| `COGNITIVE_TAG_ENDPOINTS='http://localhost:8901*'` | ""(cache_tags.py:6) | M4.3 研究线缓存标记 | **端口 8901 OPEN（本次实测）** | 研究线收口时随撤 |

### 3.5 Web/隧道/浏览器/飞书
| 变量=值 | 代码默认(读取点) | 用途/依据 | 验证 | 回收条件 |
|---|---|---|---|---|
| `WEB_AUTH_REQUIRE=1` + `WEB_LOGIN_PASSWORD_HASH=pbkdf2…` | ""(auth.py:72,56) | 隧道暴露的认证门（2026-09-04 起） | 登录日常在用 | 隧道拓扑变更时 |
| `WEB_ORIGIN_ALLOWLIST=https://app.llmfirstloop.com,…` | ""(auth.py:74) | 2026-09-30 双主机名白名单 | 403/放行路径日常在证 | 域名变更时 |
| `WEB_SESSION_COOKIE_DOMAIN=llmfirstloop.com` | ""(auth.py:252) | 同上 | 同上 | 同上 |
| `WEB_CANONICAL_HOST=llmfirstloop.com` | ""(auth.py:286) | 2026-09-30 分裂事故修复（308+https 升级） | 同上 | 同上 |
| `LFL_BROWSER_PERCEPTION_CDP_URL=http://127.0.0.1:9229` + `LFL_BROWSER_ACTION_ENABLED=1` | ""/false(config.py:1012,1023) | 2026-10-06 SMC 浏览器挂载 | **端口 9229 OPEN（本次实测）** | 挂载实例更换时更新（注释含回滚法） |
| `FEISHU_OUTBOUND_ENABLED=true` | "false"(tools_feishu…) | EVO-20260813 主动出站 | 出站限速在证 | 出站策略变更时 |
| `LFL_WEB_PROVIDERS_MODULE=lfl_web_providers.registration` + `…_MODULE_PATH=…/lfl-web-providers/src` | ""(config.py:1130,1132) | 2026-10-14 web-carveout M3 剥离 | 动态加载失败分级有兜底 | 外部项目迁移时更新 |

### 3.6 路径锚定与外部工具
| 变量=值 | 代码默认(读取点) | 用途/依据 | 验证 | 回收条件 |
|---|---|---|---|---|
| `LFL_DATA_DIR=~/…/data` | "data"(scheduler.py:33) | 2026-09-29 唯一区锚定（EVO-20260830 split-brain） | 数据落盘位置日常在证 | 仓库迁移时更新 |
| `EXPERIENCES_DIR=…` + `METHODS_DIR=…` | (paths.py:155-156, service_control.py:3655) | 2026-09-22 dual-root knowledge 显式绑定 | knowledge_health 消 quarantine | 同上 |
| `LFL_FLEET_WORKSPACE_ROOT=…/data/fleet-workspaces` | ""(config.py:1007) | 2026-09-19 slice4 fleet 接线 | spawn 回执在证 | fleet 下线时随撤 |
| `LFL_LFRT_CLI=~/Project/research/runtime/lfrt` | ""(config.py:1061) | 本地模型运行时 CLI（research 线） | 本地栈已弃用 → ⚠ 见 §5 | 随本地栈裁决 |
| `FUYAO_API_KEY=sk-fuyao-…` | ""(tools/fuyao_api.py:115) | 同花顺 Financial-API | 按需读取 | 不再使用时删除 |

### 3.7 必填凭证（注册表/桥消费，非默认概念）
`LLM_API_KEY`、`LLM_BASE_URL`（L0 合成兜底，⚠ 见 §5-2）、`DEEPSEEK_API_KEY`（providers.json deepseek）、`GLM_API_KEY`（providers.json glm）、`MINIMAX_API_KEY`（providers.json minimax + vision.py:85）、`FEISHU_APP_ID/SECRET/OWNER_OPEN_ID`（feishu/config.py:53-65）。

## 4 保留项——显式默认组（=DEF，自文档保留）

`LLM_MAX_ITERATIONS=500`、`LLM_TIMEOUT_S=120`、`TOOL_TIMEOUT_S=60`、`SELF_INSPECTION_ENABLED=1`、`STATUS_REPORT_COOLDOWN_S=60`、`SUMMARY_MODE=off`、`EMBEDDING_API_KEY=`、`EXTRACT_ENABLED=1`、`EXTRACT_INTERVAL_MSGS=20`、`EXTRACT_COOLDOWN_S=600`、`EXTRACT_TIMEOUT_S=60`、`VALIDATE_SEMANTIC=0`、`SELFHEAL_MAX_ATTEMPTS=3`、`SELFHEAL_MAX_PER_ROUND=6`、`PARAM_ADJUST_PER_ROUND=3`、`EVOLVE_ENABLED=1`、`EVOLVE_EXEC_WHITELIST=`、`SELF_EVAL_ENABLED=1`、`SELF_EVAL_MIN_SAMPLES=5`、`SELF_EVAL_SPAN=50`、`EXEC_ALLOWLIST=`、`FEISHU_WS_ENABLED=1`（默认"1"，feishu/config.py:12）、`FEISHU_OUTBOUND_RATE_PER_MIN=5`、`COMPACT_RATIO=1.0`、`COMPRESS_TARGET_RATIO=0.6`（默认 0.6，config.py:895，人工复核修正机械比对误报）、`CACHE_HIT_SHOW_IN_ANSWER=false`、`FIX_LOOP_ENABLED=0`、`WEB_PORT=8903`、`WEB_SESSION_TTL_SECONDS=43200`（=12h，auth.py:47）、`METHOD_REFLECTION_MODE=auto`（=默认，注释已修正）、`SEMANTIC_ARCHIVE/METHOD/DOCS_ENABLED=0`、`LFL_BROWSER_ATTESTATION_MODE=enforce`（=默认，config.py:1021）、`LFL_BROWSER_PERCEPTION_TARGET_ID=`、`LFL_BROWSER_PROFILE_CLASS=`。

处置：全部保留（显式写出默认值=配置自文档+防漂移锚点，非「加了就忘」残留）。

## 5 需用户确认（本次不擅动）

1. **`EVOLVE_LOCAL_EXEC=2`**：全面执行档，非默认（默认 0=仅建议）。全库与 docs 未检索到「为何开到 2」的显式决策记录（.env 不入 git 无历史）。请裁决：维持（补一句决策注释）/ 降级 1（白名单档）/ 回 0。
2. **`LLM_BASE_URL`/`LLM_API_KEY` 仍指向 deepseek**（api.deepseek.com + deepseek key）：与 2026-10-14「弃 deepseek」裁决并存。若 L0 合成兜底仍需保留则属正常；若裁决意图是彻底不指向 deepseek，可改指 GLM 端点或留待 LLM_MODEL 缺省路径自然退役。
3. **providers.json 的 `cognilocal` 空壳条目**（无模型、无 key_env）：本地模型栈 2026-10-14 弃用后的注册表残留（非 .env 范围，登记待清理）。

## 6 后续待办

1. `COMPRESS_TARGET_RATIO`：0.6 vs 0.7 的 A/B（.env 注释自留待办，迄未启动）——0.6 现与代码默认一致，转正后此行可删。
2. 生效时机：本次删除全部为零读取死配置（行为零差），无需紧急重启；`.env` 变更在下一次服务重启时对新读取生效。
3. `data/tmp_inventory/` 三份扫描 JSON 保留作为结构化证据，可在下次盘点时增量复用。

## 7 回执汇总

- 删除：11 行（10 配置项），逐行唯一匹配命中后删除；删后断言「无任一被删变量仍以生效行存在」通过。
- 备份：`.env.bak-20261014-133458-inventory`（18710 字节，与原文件字节一致）。
- sha256: pre `a91236363448c8d51e15f79d1c8c7b90cf9ae8e107fa52600369cfd3ede07036` → post `7ed306375272df4bdad3df205ef9a1b32237c1ceb833af899683ea058104ffb9`。
- 基础设施活性实测：8765(EMBEDDING bge) OPEN ｜ 8901(COGNITIVE_TAG) OPEN ｜ 8903(WEB) OPEN ｜ 9229(browser CDP) OPEN。
- 生效赋值计数：96 → 86。

---

## 附录 A：遗留处置收口（2026-10-14 14:00–14:20，依据用户裁决）

§5 三项待确认的用户裁决及执行结果：

### A1. EVOLVE_LOCAL_EXEC：2 → 0 ✅ 已执行
- 处置：`.env:77` 改为 `EVOLVE_LOCAL_EXEC=0` + 裁决注释（原 2 档全库无决策记录支持；需自动执行时显式提级）。
- 生效点：Settings 启动装配（冻结），**下次自然重启后生效**；当前进程重启前仍按 2 运行。
- 证据：grep 断言行 77 命中；edit_file diff 回执（+1/-1）。

### A2. LLM_API_KEY / LLM_BASE_URL：否决直接删除，改为注释修正 ✅（与裁决意图存在技术冲突，如实记录）
用户裁决"早期 deepseek 设定，不适应了"。删前消费方核查发现**不可直接删行**：
- `config.py:808-828`：load_settings **无条件必填校验**——缺失即 `ValueError("缺少必填环境变量: LLM_API_KEY, LLM_BASE_URL…")`，启动/热重载直接失败（与 `tests/unit/test_m50_three_end.py:622` 注释互证：缺二者走[重载失败]路径）。
- `providers.py:1030-1050`：L0 合成兜底消费二者（`api_key_env="LLM_API_KEY"`）。装配优先级 `providers.py:5`：MODEL_PROVIDERS env > providers.local.json > providers.json > L0 合成——正常路由走 registry 时，这两行只是"过校验的占位"。
- `factory.py:450`：注释明确"保持 env 三件套（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL, 零回归）"。
- 处置：**保留两行原值**（deepseek 端点+key 不动，避免 L0 兜底万一触发时 key/endpoint 失配）；将 `.env:1` 误导注释（"缺省默认 deepseek-v4-flash"）改写为准确语义（必填校验项 + 仅兜底消费 + 弃 deepseek 裁决关系 + 删除前置条件=先移除必填校验的代码改造）。真删除需另立代码任务，超出本次配置面授权范围。
- 证据：上述三处源码原文；edit_file diff 回执（+3/-1）。

### A3. providers.json cognilocal 空壳：已清理 ✅（附双层结构修正）
- 处置：删除 `data/providers.json` 中 cognilocal 条目（models={}、default_model=""、api_key_env=""）。删后 `python -m json.tool` PASS、cognilocal 零残留、剩余 deepseek/glm/minimax；refresh_config 重载成功无报错。
- **执行中修正（重要）**：model_catalog 显示 registry 仍含 cognilocal（2 模型）——溯源发现注册真源是 **`data/providers.local.json`**（本机覆盖文件，`providers.py:5` 优先级高于 providers.json）。该文件中 cognilocal 为**活条目**（Ornith-1.5-35B-A3B-MLX / qwen3.8-flash-next，弱模型对照档，evolution 准入契约 `tools_evolution.py:138` 引用）。结论：providers.json 中的 cognilocal 是被 local 遮蔽的空壳副本，删除=零行为差；local 文件的 cognilocal 非空壳、不在本次授权范围，未触碰。
- 证据：providers.json sha256 `3fa51b68…` → `bd60fe9f…`；JSON 校验 PASS；refresh_config 回执 5 provider/28 模型，与 providers.local.json 完全对账（2+3+3+2+18=28）。

### A4. 终态与后续
- `.env` 终态：270 行，sha256 `d23d51abd53f0b28c9cc597e8a22cfaec4f155bdc475fad41c55814301fc0407`（附录编辑前基线 `7ed30637…`；盘中备份 `.env.bak-20261014-133458-inventory` 仍在）。
- `data/providers.local.json` 未触碰。
- 重启回执确认（§6-2 同款，非必须）：EVOLVE_LOCAL_EXEC=0 与默认 client 绑定变更（refresh_config 已提示需重启）均在下次自然重启后生效；预期行为差仅为演进自动执行档回落 0，其余无差。
- 方法沉淀：「配置面审计·闭环三件套+三问收口」已存为 method 候选，供下次配置审计复用。
