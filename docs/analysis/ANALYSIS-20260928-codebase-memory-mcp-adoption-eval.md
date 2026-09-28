# 评估：codebase-memory-mcp 作为本仓库代码导航层的适配性（未安装）

- 日期：2026-09-28
- 方法：上游来源取证（GitHub `README.md` / `docs/llms.txt` / releases API，抓取窗口 2026-09-28 09:17–09:20，会话 Evidence 存档）+ 本仓库本地命令实证（2026-09-28 09:19–09:43）
- 状态：**纯评估**。未下载二进制、未安装、未索引、未注册 MCP、未跑 pilot。§2 的能力条目为上游自述（volatile，未逐项对 schema 复核）；§4 的收益/风险为结构性推理 + 本地实证，**未经本仓库实测**。
- **收口结论（R7，2026-09-28）**：**不引入**。原判"值得受控 pilot"所依赖的前提是"跨文件调用链 / 改动影响面在本仓库能力为零"——该前提已**被证伪**：`pyright-langserver` 早已随 dev 依赖装好（`pyproject.toml:22`），接出来即得跨文件 references 与 callHierarchy。替代实现已落地并实测：`scripts/code_nav.py` + `skills/code-nav/SKILL.md`（见 §6′）。本文件保留为"为什么否决"的取证记录。
- 对象：`DeusData/codebase-memory-mcp`，最新 release `v0.11.0`（release id 389354981），MIT

## 修订记录（本文件自创建以来的结论变动）

| # | 位置 | 变动 | 依据 |
|---|---|---|---|
| R1 | §3 末 | 撤回"~120× token 节省（3,400 vs 412,000）"数字——未在 README/llms.txt 复核到，本文不采用 | 上游页面复核 |
| R2 | §4.4 | 推翻上一轮"`.backup` 未被 `.gitignore` 忽略"——三路交叉验证证明被忽略 | 本地命令回执 |
| R3 | §4.4 / §1 | 修正 R2 的**失效机制归因**：不是"裸目录名"，而是 `check-ignore` 默认 consult index（路径被追踪或目录含 tracked 内容即假阴性）；"尾斜杠/子路径"不是解药，唯一与追踪状态无关的判据是 `--no-index` + 交叉验证。新增事实：`.backup/` 内 3 个文件先入库（2026-08-28）、规则后加入（2026-09-09）——gitignore 对已 tracked 文件无效 | 2026-09-28 二轮复核（`git blame` / `git ls-files` / `check-ignore` 矩阵） |
| R4 | §4.3 / 结论速览 | 风险 2/3 重定位：`.cbmignore` 由"硬前置"降级为 belt-and-braces（体积大头已被 `.gitignore` 兜底）；数据面真实落点 = `.git/info/exclude` 覆盖路径 + 未跟踪未忽略集（790 文件 / 7.6 MB） | 2026-09-28 二轮复核（`git ls-files -o --exclude-standard` / 逐条规则归属） |
| R5 | §4.3 / 结论速览 | 补计常驻 tool schema 成本（原漏）：17 个 MCP 工具 ≈ +8K~+16K chars/轮（当前基线 74 工具 / 37977 chars / 63295 reserve tokens） | `data/event_logs/*/request.meta`（4 会话一致） |
| R6 | §6 | 推荐顺序修正：先握手验证（+ 可选零安装对照）→ 再决定 pilot | 逻辑前置关系 |
| R7 | §6 / 结论速览 | **改判：否决引入 CBM**。§6 原 0/1/2 三选项全部作废；替代实现 = 已装 `pyright-langserver` 的 LSP 按需驱动（`scripts/code_nav.py` + `skills/code-nav/SKILL.md`） | 用户裁决 2026-09-28 + 落地实测（§6′） |
| R8 | §4.3-5 | 常驻成本补"对照项"：LSP 路径**零常驻**（不注册工具、不进每轮请求前缀、不建索引，每次调用起停子进程），与 MCP 侧 +8K~+16K chars/轮 构成同能力对照 | 落地实测 |
| R9 | 本文件外（上一轮口头结论） | 撤回两条未复现 / 误判的口头数字：① "`references(ToolResult)` 608 点 / 77 文件、冷 2.4s" → 实测稳定为 **726 点 / 82 文件、查询 0.26s**（3 次独立复现）；② "callHierarchy 行号不可信（报 `guard.py:1`）" → 实为把 `selectionRange`（函数定义行）与 `fromRanges`（调用点行）互相比，属**误判**；20/20 抽样核对零错位 | 2026-09-28 三轮 LSP 实测（§6′ / §7） |
| R10 | §6′ / `scripts/code_nav.py` / `skills/code-nav` | **原型 hardening 收口**：撤回 `222 行 / 67 文件 = program 范围外缺失` 的说法；该算法混入 ignored `.codeartsdoer`、`src` 内 lexical-only 与非 repo-visible 路径。改为 `git ls-files -co --exclude-standard -- *.py` 的 repo-visible lexical universe，并把 lexical candidates 与 semantic refs 分开。同期修复 readiness rc=0、cwd-relative path、outgoing call site/target 混淆、多 `fromRanges` 丢失、同名/多 hierarchy item 歧义、managed worktree 找不到共享 Pyright、LSP reader/process fail-fast、graceful shutdown、repo 并发锁等。Phase 2 真实 canary：Pyright 1.1.411；ToolResult 729 locations / 82 files；lexical complement 153 occurrences / 153 lines / 47 files，其中 include 外 150 / 44；callers 21；callees 361；`--ready-timeout 0` rc=1。**这些 exact counts 只是一时 baseline，不是 release invariant。** | `CODE-NAV-PHASE2-ACCEPTANCE-20260928.json` + 14/14 hardening tests |

## 结论速览

| 问题 | 结论 |
|---|---|
| 平台可用？ | 可用。本机 macOS 26.5.1（Build 25F80）/ `Darwin 25.5.0 arm64`；v0.11.0 资产含 `codebase-memory-mcp-darwin-arm64.mcpb`（另有 macOS x64 / Linux / Windows） |
| 怎么接？ | 两条路：① 本仓库自带 stdio MCP 客户端（原生能力，非旁路）；② 一次性 `cli <tool>` 通道（不驻留进程，更贴合 LFL 的 evidence 通道） |
| 值不值得装？ | **不装（R7 收口）**。"跨文件调用链 / 改动影响面在本仓库能力为零"这一前提**已证伪**：`pyright-langserver` 早已是 dev 依赖，接出来即得跨文件 references + callHierarchy。剩余空白（死代码、架构总览、语义检索、多语言）不足以承担下面三项代价 |
| 主要成本 | ① 默认 `install` 会写 45 个客户端面（39 自动探测 + 6 条件/显式）的 MCP 条目、指令、skills 与 hooks；② **常驻 tool schema**：17 个工具以 `mcp_<server>_<tool>` 注册后每轮请求全量携带，估算 +8K~+16K chars（当前基线 37977 chars / 74 工具，见 §4.3-5）；③ **对照项（R8）**：同一能力的 LSP 路径为**零常驻**——不注册工具、不进每轮请求前缀、不建索引，每次调用起停子进程（实测见 §6′）。索引忽略面经二轮复核由 `.gitignore` 基本兜底（`.cbmignore` 为 belt-and-braces，非硬前置） |
| 建议 | 见 §6′（R7 改判）：CBM 路径（原 §6 的 0/1/2 三选项）**全部作废**；替代实现 `scripts/code_nav.py` + `skills/code-nav/SKILL.md` 已落地并实测。原 §6 保留为过程记录 |

## 一、为什么评估它（本仓库的导航现状）

实证（2026-09-28 本地命令）：

- 代码导航现役能力只有 4 个：`search_files`（文件名 glob / 文本）、`read_file`、`inspect_code`（**单文件或目录** AST：类/函数/签名/imports，实现在 `src/llm_loop/tools/builtin/inspect_code.py`）、`git grep`。
- `src/` 内检索 `call_graph|callers_of|call_edges|impact_analy|blast_radius` → **命中 0**：没有跨文件调用图、没有符号级影响面分析。
- 仓库内检索 `codebase-memory`（2026-09-28 09:2x，**本文件落盘前**）→ **命中 0**：此前无相关评估或试点记录。（自指说明：本文件落盘后该串会命中本文件自身——"0"是落盘前时点的检索回执。）
- 规模：tracked 文件 3,244；tracked `.py` 1,377 个 / **363,978 行**；`.ts`+`.tsx` **19,008 行**。

也就是说：**"这个函数谁在调"/"改这个文件会波及什么"/"哪些代码是死的"/"入口和路由长什么样"，今天只能靠 grep + 单文件 AST 手工推。** 这正是被评估对象声称覆盖的部分。

## 二、上游自述能力（README / llms.txt）

（阅读指引：本节为上游自述全文，volatile、供追溯；决策导向阅读可跳 §1 → §4 → §6。）

### 2.1 MCP 工具（README「MCP Tools」表，共 17 个）

索引类 5 个：

| 工具 | 作用 | 已知关键参数 |
|---|---|---|
| `index_repository` | 把仓库索引进图，之后自动保鲜 | `repo-path` |
| `list_projects` | 列出已索引项目与节点/边计数 | 无入参（不读 stdin） |
| `delete_project` | 删除项目及其全部图数据 | — |
| `index_status` | 查询索引状态 | — |
| `check_index_coverage` | 精确路径/范围是否已索引且新鲜；"干净"不等于完整性证明 | — |

查询类 12 个：

| 工具 | 作用 | 已知关键参数 |
|---|---|---|
| `search_graph` | 结构 + BM25 + 语义搜索（含 `semantic_query` 向量检索） | `project`、`name_pattern`、`label`、`offset/limit`、`semantic_offset/semantic_limit` |
| `trace_path`（别名 `trace_call_path`） | BFS 调用链：谁调它 / 它调谁，深度 1–5 | `function-name`、`direction` |
| `detect_changes` | git diff → 受影响符号 + 爆炸半径 + 风险分级 | 快照绑定 `*_cursor`（拒绝漂移，不静默跳行） |
| `query_graph` | 只读 openCypher 子集 | `query` |
| `get_graph_schema` | 各标签节点/边计数、关系模式、属性定义（官方建议第一个跑） | — |
| `compare_graphs` | 两个快照 diff（增删节点/边） | — |
| `get_code_snippet` | 按限定名取源码 | 限定名 `..`，先用 `search_graph` 发现 |
| `get_file_outline` | 单文件声明大纲（源码序，可过滤/分页） | — |
| `get_architecture` | 语言/包/入口/路由/热点/边界/层/聚类总览 | — |
| `search_code` | 索引内 grep 式文本搜索 | `result_limit/offset`、`raw_limit/offset`、`raw_content_offset`、`directory_limit/offset` |
| `manage_adr` | ADR 增删改查 | 模式 `get/update/set_sections/sections`；`set_sections` 只改命名小节 |
| `ingest_traces` | 摄入运行时 trace，校验 `HTTP_CALLS` 边 | — |

（参数名取自 README 表格文字，未逐个对 input schema 核对。）

### 2.2 图模型与查询

- 节点：`Project` / `Package` / `Folder` / `File` / `Module` / `Class` / `Function` / `Method` / `Interface` / `Enum` / `Type` / `Route` / `Resource`。
- 边：`CONTAINS_*`、`DEFINES`、`IMPORTS`、`CALLS`、`CALL_REFERENCE`、`HTTP_CALLS`、`ASYNC_CALLS`、`IMPLEMENTS`、`HANDLES`、`USAGE`、`CONFIGURES`、`REFERENCES_FILE`、`WRITES`、`MEMBER_OF`、`TESTS`、`USES_TYPE`、`FILE_CHANGES_WITH`；另有语义边 `SEMANTICALLY_RELATED`、`SIMILAR_TO`（MinHash+LSH）与跨仓库 `CROSS_*`。
- `query_graph`：只读 openCypher 子集——`MATCH/WHERE/WITH/RETURN/UNWIND/UNION`、变长路径、聚合、`EXISTS{}`（可写死代码查询）；写语句被拒。
- 语义检索：自带 `nomic-embed-code`（768 维）编译进二进制，11 信号打分，**无 API key、无 Ollama、无 Docker、不自行联网**。

### 2.3 语言与解析

- 语言数：README 徽章/正文称 **162**；README 索引管线小节称 **158 个 vendored tree-sitter 语法**；llms.txt 称 **158**（见 §3）。
- Hybrid LSP 类型解析：README 点名单 **12** 项（Python、TS/JS/JSX/TSX、PHP、C#、Go、C、C++、Java、Kotlin、Rust、Perl）；llms.txt 称 **9 个语言族**。

### 2.4 运行面（与本次评估相关的部分）

- 索引范围与忽略：硬编码 → `.gitignore` 层级 → `.cbmignore`；探测式规则：绝不索引"零可索引文件"的仓库（README 未提 `.git/info/exclude`，见 §5）。
- 协同 daemon：首个 MCP 会话启动账户级 daemon，后续会话作为瘦客户端接入；每个二进制启动时校验 `metadata.db` 版本，不匹配自动重启；`--no-daemon` 可关；`daemon stop` 手动停。
- Watcher：`auto_watch`（默认 true，按会话生效）、`watcher_enabled`（默认 true，daemon 启动时读一次，改后需 `daemon stop`）、`auto_index`（默认 true，首次连接自动索引）、`auto_index_limit` 默认 50000、`index_max_files` 默认 0（不限）、`index_max_source_mb` 默认 16。多仓库可 `index_repository` 合并索引，支持离线 / 无 key / 无 Docker。
- 环境变量：`CBM_ALLOWED_ROOT`（限定可索引根）、`CBM_CACHE_DIR`（默认 `~/.cache/codebase-memory-mcp`，daemon 日志走 `${CBM_CACHE_DIR}/logs`）、`CBM_DIAGNOSTICS`、`MCP_CROSS_HOST=0`（禁用全局 daemon）。
- 诊断：`codebase-memory-mcp install --diagnose` 打印 schema/migrations/索引健康。

### 2.5 CLI（如果走一次性通道）

- 形态：`codebase-memory-mcp cli <tool> [flags | '<内联JSON>' | --args-file | stdin]`；每个工具的 flag 由 input schema 现场生成，`cli <tool> --help` 查看；内联 JSON 已标 deprecated。
- README 示例：`cli index_repository --repo-path /p`、`cli list_projects`、`cli search_graph --project p --name-pattern '.*Handler.*' --label Function`、`cli trace_path --project p --function-name Search --direction both`、`cli query_graph --project p --query '<cypher>'`。
- 外层开关：`--verbose / --progress / --quiet / --format json`（工具级）/ `--json`（完整 MCP 信封）；进度与日志走 stderr，stdout 只留结果。
- 语义：一次性命令**不连协调 daemon、不留常驻进程**；唯 `index_repository` 会启临时 worker 并在退出前停掉；图变更用 OS 级 per-project 锁串行化。
- 管理命令：`config list|set|reset`、`install`（`--skip-config` = 只装二进制不碰 agent 配置；`--dir=` 自定义位置）、`update`（不自更新，打印应跑的安装脚本路径；设计理由：二进制不下载自己，发布包不含下载 URL，**CBM 不主动联网**）、`uninstall`（确认后才删索引；二进制旁的安装脚本只报告不删除）、`daemon stop`、`--ui=true --port=9749`、`--ui=0`、`--bind`。
- 安装渠道：`install.sh` / `install.ps1`（解压前校验 checksums；`install` 自动剥离 macOS quarantine 并 ad-hoc 签名）、手动 tar.gz/zip、npm、PyPI、Homebrew、Scoop、Winget、Chocolatey、AUR、`go install`。平台门槛（README）：Windows x64 仅 x64、最低 Win10 1809；Linux glibc ≥ 2.28（非 musl）；macOS ≥ 13。
- 兼容承诺：已发布工具名不再改名（唯一例外：`search_graph` 两个已废弃参数）；旧的 `node ... cli <tool>` 形式只剩过期 `.mcp.json` 警告。

### 2.6 性能（厂商口径，**未独立复现**）

llms.txt：Linux kernel（28M LOC / 75K 文件）全量索引 3 分钟 → 4.81M 节点 / 7.72M 边；Cypher 查询 "under 1ms"。README 页首亦写 "under 1ms"。上游另发布 `docs/BENCHMARK.md` 与 arXiv 2603.27277。

## 三、上游内部口径不一致（如实标注，不替它裁决）

| 项 | README | docs/llms.txt |
|---|---|---|
| MCP 工具数 | **17**（徽章 + 17 行表格） | **15**（"MCP tools: 15"，只列 8 个 + "and more"） |
| 语言数 | 徽章/正文 **162**；索引管线 **158 vendored grammars** | **158** |
| Hybrid LSP | 点名单 **12** 项 | **9 个语言族** |

消歧口径：以安装后 `codebase-memory-mcp cli --help` / MCP `tools/list` 的真实回执为准。本评估不据此推断任何一方"正确"。

（修订记录：本会话上一轮口头摘要中出现的 "~120× token 节省（3,400 vs 412,000）" 数字，本轮取证未在 README/llms.txt 页面中复核到，**本文不采用**；如需该口径请直接读上游 `docs/BENCHMARK.md`。）

## 四、对本仓库的适配性

### 4.1 可用性（已核实）

- 平台：macOS 26.5.1 / arm64，v0.11.0 提供 darwin-arm64 资产 → 可运行。
- 接入：本仓库自带 stdio MCP 客户端 —— `MCP_SERVERS`（env JSON 数组）配置 stdio 服务器，启动时握手 + 拉取工具清单，以 `mcp_<server>_<tool>` 注册进 `ToolRegistry`（源码：`src/llm_loop/tools/mcp_client.py`；`_HANDSHAKE_TIMEOUT_S = 15.0`、`_CALL_TIMEOUT_S = 120.0`、结果五态包装 `success/failure/blocked/timeout/error`、**fail-open**（服务器连不上只是工具未注册，不拖垮会话）、失联重连一次、运行中可 refresh 增删工具）。也就是说：注册 CBM 是走既有协议路径，属原生接入。

### 4.2 收益分层

- **真增益（原判"现仓库为零"——R7 已部分证伪，逐条重列）**：
  - ~~谁调用谁（`trace_path`）~~ → **已覆盖**：`pyright-langserver`（dev 依赖）经 `scripts/code_nav.py callers` 可得。原型阶段 R9 观测为 20 callers / 0.84s；R10 hardened 快照为 21 callers。exact count 随代码演进，不作为能力门（见 §6′）。
  - **仍是真的空白**：① 按 **git diff 反推**受影响符号与爆炸半径并分级（`detect_changes`）——本仓现在只有"按符号查调用者"，没有"按改动面反推"；② 死代码（Cypher `EXISTS{}`）；③ 入口/路由/架构总览（`get_architecture`）；④ 语义检索（`nomic-embed-code`）；⑤ 多语言（上游 12 项 vs 本仓 LSP 目前仅 Python 可用）。
  - **低增益**：`get_code_snippet`（`read_file` 已够）、`search_code`（`search_files` 已够）、找文件 / 找文本。
- **别当真**：所有延迟/规模/省 token 数字（§2.6）都是厂商口径；本仓库 0.36M 行，离其主打的 28M 行内核场景差两个数量级，**"毫秒级"不是本仓库的诉求**。
- **召回率存疑**：本仓库大量 registry / dispatch 动态分发，`CALLS` 边在静态图里同样可能漏——**这一点对 LSP 同样成立**（`getattr` / 注册表 / 字符串分发，两者同级无解，见 §6′）。

### 4.3 风险与成本

1. 默认 `install` 会探测并写入 45 个客户端面（39 自动 + 6 条件）的 MCP 条目、指令、skills 与 hooks —— 本机若有其他编码客户端会被改动。规避：`--skip-config` 只装二进制，或直接手动解压（压缩包内含 `install.sh`，可选 `--dir=`）。
2. 索引忽略面（本地实证；2026-09-28 二轮复核后重定位）：`.gitignore` 已覆盖 `data/*`(17)、`.env`(23)、`.env.bak*`(25)、`.venv`(71)、`.backup/`(76)、`.worktrees/`(93)、`/tmp/`(116)。体积大头均在此层（`.venv` 1.6G、`.worktrees` 3.3G、`data` 7.2G、`tmp` 444M、`.git` 490M），而 CBM 按自述尊重 `.gitignore` 层级 → **`.cbmignore` 是 belt-and-braces（双保险），不是 pilot 硬前置**（原"需先解决索引忽略面"表述降级）。`.git/info/exclude` 实测 11 条中 10 条存在、1 条缺失（`/.tmp-truncation-recoverability-p0/`）；除 `.backup/` 与 `.gitignore` 重叠外，其余 9 条是 `.gitignore` 覆盖不到的面——残余风险见下条。
3. 数据面（重定位）：索引库落本地 `~/.cache/codebase-memory-mcp`（含代码片段）；CBM 不主动联网、无 API key。**敏感面落点不在 `.venv`/`.worktrees`（已被 `.gitignore` 覆盖），而在两处忽略层残余**：
   - `.git/info/exclude` 覆盖、`.gitignore` 覆盖不到的路径（CBM 是否读 exclude 未验证）——实测存在 10 条，需先看：`cloudflared/config.local.yaml`（4K，本地隧道配置）、`scripts/setup-llmfirstloop-tunnel.sh`（8K）；大件：`data_ab/`（23M，GLM/minimax A/B 实验数据）、`.tmp-ci/`（404K）、`scripts/forensics/out/`（52K）等。
   - **未跟踪且未忽略的 790 个文件 / 7.6 MB**（`git ls-files -o --exclude-standard` 实测）——无任何忽略层覆盖，会被 CBM 索引；最大宗为 `evals/execution_efficiency_fcr/*.jsonl`（评测原始数据，单文件最大 948K）。
   - 补充：`.backup/` 内 3 个已 tracked 文件不受 `.gitignore` 约束（见 §4.4）；若 CBM 对 tracked 内容有特殊语义，需单独确认（未验证）。
   → pilot 前建议把 `.git/info/exclude` 关键项（尤其上述两文件 + `data_ab/`）抄进 `.cbmignore`，而不是指望 exclude 被尊重。
4. 超时：MCP 通道调用上限 120s，`index_repository` 在 0.36M 行 / 3,244 文件规模下大概率够用，但这是本仓库客户端契约的潜在瓶颈（daemon 路径则不受此限）。
5. **常驻 tool schema 成本（补计，原漏）**：MCP 注册的工具以 `mcp_<server>_<tool>` 常驻工具表，每轮请求的 `tools` 参数全量携带 schema，其字符数经 `src/llm_loop/core/loop/engine.py:1010` 计入输入预算（`tool_schema_reserve_chars` → `tool_schema_reserve_tokens`），并直接压缩 history 预算。当前实测（2026-09-27/28 四个会话一致）：`tools_count=74`、`tool_schema_reserve_chars=37977`、`tool_schema_reserve_tokens=63295`（projection_fallback 口径）、`pre_tool_history_budget_chars 141557 → effective 103580`（schema 吃掉约 26.8% 可用输入预算）。CBM 的 17 个工具在此常驻项上**净增约 +8K~+16K chars（估算区间）**＝当前值的 +21%~+42%，每轮携带。与 §4.2"厂商省 token 数字不可信"同理：**引入侧成本的 token 账必须自算**。
   **对照项（R8）**：同一能力若走已装 `pyright-langserver` 的 LSP 路径，此常驻项为 **0**——不注册工具、不进每轮请求前缀、不建索引；代价转移成每次调用起停子进程的一次性开销。R8/R9 原型观测曾为 `doctor` 0.4s、`refs ToolResult` 0.61s、`callers` 0.84s；这些延迟只保留作历史量级证据，R10 不把 exact latency/count 当 release invariant（见 §6′）。两条路径的 **token 账与延迟账方向相反**，应当并列看，不能只算一边。

### 4.4 一处方法性校正（两轮：先推翻结论，再修正归因）

**第一轮（结论翻转）**：上一轮口头摘要称"`.backup` 未被 `.gitignore` 忽略"——**该结论错误**。`.backup/` 确由 `.gitignore:76:.backup/` 覆盖，三路交叉验证：

- `git status --porcelain --ignored=matching -- .backup` → 未跟踪内容标 `!!`；
- `git ls-files -o --exclude-standard | grep -c '^\.backup/'` → `0`；
- `git check-ignore --no-index .backup/` → `.gitignore:76:.backup/`。

**第二轮（归因修正，2026-09-28）**：上一轮把失效原因归为"裸目录名"、并把"尾斜杠/子路径"当作解法——**该归因错误**。实测矩阵（`.backup/` 下含 3 个 tracked 文件）：

| 命令 | rc | 命中 | 行为 |
|---|---|---|---|
| `git check-ignore -v .backup` | 1 | — | 目录含 tracked 内容 → 假阴性 |
| `git check-ignore -v .backup/` | 1 | — | 尾斜杠**不改**判定（仍 consult index） |
| `git check-ignore -v .backup/dummyfile`（未跟踪） | 0 | `.gitignore:76:.backup/` | 未跟踪子路径 → 直接匹配规则 |
| `git check-ignore -v .backup/pollution-20260828/README.md`（已跟踪） | 1 | — | **已跟踪**子路径 → 同样假阴性 |
| `git check-ignore -v --no-index .backup` | 0 | `.gitignore:76:.backup/` | `--no-index` 跳过 index → 与追踪状态无关 |
| 对照：`git check-ignore -v .venv`（无 tracked 内容） | 0 | `.gitignore:71:.venv` | 裸目录名正常——失效与"裸名"无关 |

机制：`git check-ignore` 默认 consult index —— **路径本身被追踪、或其目录含 tracked 内容时，即使 gitignore 规则匹配也判"非忽略"**。决定性因素是 index 状态与 `--no-index`，不是路径形态。

**同轮浮出的仓库事实（此前未见）**：`.backup/` 内有 **3 个已 tracked 文件**（`.backup/pollution-20260828/{README.md,exception_polluted.jsonl,payload_trace_polluted.jsonl}`，5ad31ab7d 于 **2026-08-28** 入库，提交信息为"污染存证"），而 `.gitignore:76` 规则由 2f35e47752 于 **2026-09-09** 才加入——**晚于入库 12 天**。gitignore 对已 tracked 文件无效（不配 `git rm --cached` 就不会清出）：

- "`.backup/` 已被忽略"对目录内**新增**内容成立，对这 3 个已入库文件不成立；
- `git status --ignored` 只覆盖**未跟踪**内容（3 个 tracked 文件不出现在 ignored 视图）——交叉验证有盲区，须以 `git ls-files -- .backup` 补位。是否将 3 个存证文件移出 HEAD 属仓库治理决策，本文不裁决。

**方法教训（修订版）**：判定忽略优先用 `git ls-files -o --exclude-standard`（未忽略集）与 `git ls-files -- <path>`（tracked/untracked 分界）；用 `check-ignore` 时必须带 `--no-index`——裸名、尾斜杠、子路径都不能替代它。（附：`staging-statebraid-20260914` 同批悬置项本轮复核完毕——由 `.gitignore:106:/staging-*/` 覆盖、`git ls-files` 计数 0、裸名/`--no-index` 均 rc=0，属正常，不再列为可疑。）

## 五、未验证项（本评估的诚实边界）

1. **协议兼容**：本仓库 harness 的 MCP 版本与 CBM 服务端是否握手成功——未实测。
2. `.git/info/exclude` 是否被 CBM 忽略层尊重——README 未提，未实测。
3. 动态分发场景下 `CALLS` 召回率、以及索引时长 / 内存 / 磁盘占用——未实测。
4. 本仓库 120s 调用超时对 `index_repository` 的实际影响——未实测。
5. `install`（默认模式）对本机已装客户端配置的具体改动面——未实测。
6. README 的 162 / 158、17 / 15、12 / 9 差异哪个是当下事实——需装后回执裁决。

## 六、原「下一步候选」（R7 后**全部作废**，保留为过程记录）

> 下面三条候选（0 零安装对照 / 1 最小入侵 pilot / 2 只验协议握手）在 R7 收口后**均不执行**。保留它们的理由：其中"0. 零安装对照"的方向后来被证实是对的，只是当时**预期严重偏低**（原文写"预期覆盖有限"）——实测远超预期。**替代实现与实测结论见 §6′。**

**原推荐路径（2026-09-28 修订，已作废）**：先做 2（只验协议握手——唯一能同时裁决 §5.1 协议兼容与 §5.6 口径冲突、且不产生索引的动作）→ 可选做 0（零安装对照，为收益评估补基线）→ 2 通过后再决定是否执行 1。

0. **零安装对照（可选，约半天）**：用仓库已有静态检查能力确认"零新增二进制"路径能覆盖 §4.2 真增益里的哪几条。已知事实：`pyright>=1.1.390` 在 `pyproject.toml` dev 依赖、且是 `scripts/ci_gate.sh` 第 3 道门（`"$PY" -m pyright`；链路 ruff → env-pin → pyright → pytest）。**边界**："谁调用它"属 LSP 引用能力（需 LSP 客户端），pyright CLI 直出的是诊断、不含调用图——预期覆盖有限，但作为 pilot 的对照基线成本极低。
1. **最小入侵 pilot**（原推荐；现以 2 通过为前提）：`--skip-config` 装二进制（或手动解压到独立目录）→ 写 `.cbmignore` → `cli index_repository` → 用 3 个真实问题与 grep + 单文件 AST 对照：
   - a) `src/llm_loop/tools/registry.py` 的 tools 注册链路谁调用谁；
   - b) 改 `src/llm_loop/pipeline.py`（或等价热点）的爆炸半径；
   - c) 用 `EXISTS{}` 查死代码，抽样人工核对命中真伪。
   对照维度：正确性、召回（漏了什么）、耗时、token 消耗（含 §4.3-5 的常驻 schema 增量与 history 预算压缩）。
2. **只验协议握手（建议先做）**：在 `MCP_SERVERS` 加一条 CBM（走 `cli` 或原生 stdio），确认工具注册、五态包装、常驻 tool schema 实际增量与 120s 超时行为，再决定要不要放索引。
3. **到此为止**：把本文件当结论，不投入安装。（R7：此条即最终裁决。）

## 六′、替代实现：按需 Pyright 语义导航（R7 决策，R10 hardened）

### 6′-1 定位：不是 repo 全量真相，而是带可信边界的语义导航器

`pyright>=1.1.390` 已是本仓 dev 依赖，生产 hardening 验证使用 `pyright 1.1.411`。本方案复用其 `referencesProvider` / `callHierarchyProvider`，仍保持：**零常驻 MCP tool schema、零持久索引、按需起停**。

R10 后不再把 `code_nav.py` 描述成“给出 repo 全部引用”。正式契约分三层：

1. **analysis readiness**：当前 Pyright 已验证链为 `initialize -> initialized -> didOpen -> publishDiagnostics(target)`。未 ready 必须非零失败；
2. **semantic scope**：LSP 结果只声明在当前 Pyright program/config scope 内成立；
3. **repo-visible lexical candidates**：`refs` 默认用 `git ls-files -co --exclude-standard -- '*.py'` 构造独立文本 universe，辅助暴露 scope 外/语义外候选，但不能叫成“Pyright 漏掉的 reference”。

`publishDiagnostics` 是 **Pyright 1.1.411 上通过 fixture + 真实仓库召回对照验证的 readiness contract**，不是 LSP 规范定义的通用“workspace 索引完成”保证。升级 Pyright 后必须重跑真实 fixture/canary。

### 6′-2 落地物与运行边界

| 文件 | 作用 |
|---|---|
| `scripts/code_nav.py` | 按需 LSP 客户端；`doctor` / `refs` / `callers` / `callees`；Python 实现零新增第三方包 |
| `skills/code-nav/SKILL.md` | 可信度规则、使用方法、字段语义、盲区与固定核验动作 |
| `tests/fixtures/code_nav_fake_lsp.py` | 协议状态机 fixture：`initialized`、server request、提前退出、malformed frame 等 |
| `tests/unit/test_code_nav_hardening_red.py` | correctness/hardening 回归测试 |

运行仍依赖 `git` CLI 与已安装的 `pyright-langserver`。managed worktree 通常没有本地 `.venv`，脚本按顺序查：code-root venv → Git common-root 共享 venv → PATH。真实 hardening canary 已确认 source=`git_common_root_venv`。

### 6′-3 R10 hardened 真实基线（2026-09-28）

基线来自 production gen159 `889634f21...` 派生的 clean hardening worktree；**只作观测，不作 exact-count gate**。

| 项 | 实测 |
|---|---|
| `doctor` | `status=ok`、ready=true、Pyright `1.1.411`、source=`git_common_root_venv` |
| `refs ToolResult` | **729 semantic locations / 82 files** |
| root vs `scripts/` 子目录调用 | semantic locations 完全一致 |
| repo-visible lexical complement | **153 occurrences / 153 lines / 47 files** |
| configured include=`src` 内 lexical-only | 3 occurrences / 3 files |
| configured include 外 lexical-only | **150 occurrences / 44 files** |
| `callers workspace_base` | **21 callers** |
| `callees build_engine` | **361 outgoing entries**；多 `fromRanges` 完整保留 |
| `--ready-timeout 0` | **rc=1 / `status=not_ready`** |
| hardening suite | **14/14 PASS** |

R9 的 726/82 与 20 callers 是前一原型快照的实测，不是“错数”；R10 代码基线发生演进后变成 729/82 与 21。两组数字都不能当永久真值。

### 6′-4 原型阶段三类误导已被消除

**① readiness 不再“提醒后继续”。**

原型可出现 `readiness=false` 但 rc=0，并继续返回早期 1 个 location。这是最危险的 silent failure。R10 后 doctor / refs / hierarchy 未过 readiness gate 都直接 `status=not_ready`、rc=1，不执行/不接受后续语义查询。

历史三臂实验仍保留其方法价值：仅 initialize → 0/0；didOpen 不等 → 1/1；等 diagnostics → 当时 726/82。它证明的是**等待分析完成对召回极其关键**，不是 726 这个数字永恒不变。

**② `222 / 67` 不再叫“范围外缺失”。**

旧 cross-check 用 `os.walk` 扫描，混入 ignored `.codeartsdoer` 快照、`src` 内 lexical-only 命中，并把 occurrence 误叫“行”。R10 后：

- universe = tracked + non-ignored untracked Python；
- 分开 `occurrences` / `matching_lines` / `matching_files`；
- 明示 `inside_configured_include` / `outside_configured_include`；
- lexical candidate 不升级成 semantic missing reference。

**③ incoming/outgoing callHierarchy 不再共用错误行号模型。**

原型 `callees` 曾把 caller 的 `fromRanges` 行号贴到 callee 文件路径上，例如伪装成 `config.py:397 -> ensure_dirs`，真实调用点其实是 `factory.py:397`。R10 后：

- callers：`site_path/site_lines` + `caller_definition_path/line`；
- callees：`site_path/site_lines` + `target_path/target_definition_line`；
- 保留全部 `fromRanges`。

真实 canary：`factory.py:397 -> config.py:731 ensure_dirs()`；`resolve` 同一 outgoing entry 保留 `[419, 1930]` 两个调用点。

### 6′-5 协议、歧义、资源与安全 hardening

R10 还补齐了第一版原型没有覆盖的边界：

- initialize 成功后必须发送 `initialized`；
- server→client 带 `id` request 必须应答；未知 request 回 `-32601 Method not found`；
- reader framing/JSON 错误、server 提前退出 fail-fast，不等满 query timeout；
- 正常结束 `shutdown -> exit`，terminate/kill 仅兜底；
- 同名 definition 或多个 `prepareCallHierarchy` item 均 fail-closed；
- 所有 repo 内路径统一相对 canonical repo root；repo 外目标与非 Python 目标拒绝；
- 同一 repo 用 advisory lock 限制并发 langserver fan-out；
- JSON 成功态统一携带 `schema=lfl.code_nav.v1`、`status`、`trust`、`semantic_scope`。

### 6′-6 与 CBM 的取舍结论不变

| 维度 | CBM（MCP） | 按需 Pyright（本方案） |
|---|---|---|
| 常驻 tool schema | +8K~+16K chars/轮（估算） | **0** |
| 索引 | 需构建、存在 freshness 生命周期 | **无持久索引** |
| Python references / call hierarchy | 有 | **有，且已 harden/验证** |
| dead code / 架构总览 / diff blast-radius | 有更高层能力 | **无** |
| 语义检索 / 多语言 | 有 | 当前仅 Python wrapper |
| 动态 dispatch | 仍有静态分析盲区 | 同样有盲区 |
| 接入风险 | 要新增 MCP/工具面 | 纯 repo 脚本 + skill，不进入每轮工具 schema |

因此 R7 的架构裁决**不变**：不为当前 Python 符号导航需求引入 CBM。R10 修正的是替代 wrapper 的 correctness 与证据口径，不是翻转 R7。

### 6′-7 已知盲区

1. `getattr` / 注册表 / 字符串 dispatch 等动态派发仍需沿注册结构人工追踪；
2. TS/JS 尚无对应 wrapper；
3. semantic scope 不是 repo-wide absence proof；`rc=2` 只表示当前 semantic scope 内查询完成且为 0；
4. lexical candidates 可能是注释、字符串或同名符号，必须回读源码；
5. 每次调用重建 program，有启动成本，不适合高频循环；
6. Pyright 升级后必须重跑 real fixture/canary，不能机械沿用 1.1.411 的 readiness baseline。

## 七、取证索引

- 外部（本会话 Evidence，抓取 2026-09-28 09:17–09:20）：
  - `https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/README.md`（分页读取 0–64K）
  - `https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/docs/llms.txt`（4,675 字符，含 158 语言 / 9 LSP 族 / 15 工具 / 45 客户端面 / MIT）
  - `https://api.github.com/repos/DeusData/codebase-memory-mcp/releases/latest`（v0.11.0，id 389354981，含 darwin-arm64 资产）
  - `https://api.github.com/repos/DeusData/codebase-memory-mcp/contents/` 与 `.../contents/docs`
- 本地（首轮 2026-09-28 09:19–09:43 命令回执）：平台 `Darwin 25.5.0 arm64` / macOS 26.5.1(25F80)；`git ls-files` 3,244；tracked `.py` 1,377 个 / 363,978 行；`.ts,*.tsx` 19,008 行；`src/` 调用图类符号命中 0；仓库内 `codebase-memory` 引用 0（本文件落盘前）；`.gitignore`/`.git/info/exclude` 忽略规则与 `git status --ignored` 交叉验证；`.cbmignore` 不存在；`src/llm_loop/tools/mcp_client.py` 的 `MCP_SERVERS` / `mcp_<server>_<tool>` / 15s / 120s / fail-open 事实。
- 本地（二轮复核 2026-09-28 17:5x 命令回执）：`git blame -L 74,78 -- .gitignore`（2f35e47752, 2026-09-09 加入 `.backup/`）；`git ls-files -- .backup`（3 个 tracked，5ad31ab7d 于 2026-08-28 入库）；`check-ignore` 矩阵（含 `--no-index` / 尾斜杠 / 未跟踪与已跟踪子路径 / `.venv` 对照）；`git status --porcelain --ignored=matching -- .backup`；`git ls-files -o --exclude-standard`（790 文件 / 7,600,617 B）；`.git/info/exclude` 逐条 `check-ignore -v --no-index` 归属；`du -sh`（`.venv` 1.6G / `.worktrees` 3.3G / `data` 7.2G / `tmp` 444M / `.git` 490M）；工具面数字取自 `data/event_logs/*/request.meta`（4 会话一致：74 tools / 37977 chars / 63295 reserve tokens）；`pyproject.toml:22` pyright 与 `scripts/ci_gate.sh:83-84` 调用点；`staging-statebraid-20260914` 复核（`.gitignore:106`，无 tracked）。
- 本地（三轮 2026-09-28 21:0x–21:1x，LSP 落地实测命令回执）：`.venv/bin/pyright-langserver` 存在（`pyright --version` → 1.1.411）；`scripts/ci_gate.sh` 的 `"$PY" -m pyright` 门；`/tmp/nav_fixture` 三文件 fixture 复现"漏发 `initialized` 则任何请求挂死"；三臂就绪门对照（0 / 1 / 726 点，3 次独立复现）；`refs ToolResult`（`src/llm_loop/core/message.py`）→ 726 点 / 82 文件、0.61s，范围外交叉检查 222 行 / 67 文件（`tests` 116、`.codeartsdoer` 78、`scripts` 17、`evals` 4、`examples` 4、`src` 3）；`callers workspace_base` → 20 调用者 / 0.84s，20/20 行号与原文逐条核对一致；`doctor` 全流程 0.4s；对照 CLI `python -m pyright` 9.2s / 25 errors；落地物 `scripts/code_nav.py` 与 `skills/code-nav/SKILL.md`。
- 本地（四轮 R10 hardening，2026-09-28）：基于 production gen159 `889634f21...` 的 clean worktree；`tests/unit/test_code_nav_hardening_red.py` 14/14 PASS；Ruff / format / py_compile / diff-check / security scan PASS；真实 Pyright 1.1.411 `doctor` ready=true、`langserver_source=git_common_root_venv`；`refs ToolResult` → 729 semantic locations / 82 files，repo root 与 `scripts/` 子目录调用完全一致；repo-visible lexical complement → 153 occurrences / 153 lines / 47 files，其中 configured include 外 150 / 44、内 3 / 3；`callers workspace_base` → 21；`callees build_engine` → 361，跨文件 site/target path 正确且多 `fromRanges` 保留；`--ready-timeout 0` → rc=1 / `status=not_ready`。正式验收证据：`docs/analysis/CODE-NAV-PHASE2-ACCEPTANCE-20260928.json`。
