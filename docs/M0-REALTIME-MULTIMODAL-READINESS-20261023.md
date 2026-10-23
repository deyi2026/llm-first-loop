# LFL 实时多模态 M0 就绪核实与探针记录

> - 特性名：`realtime_multimodal`　阶段：**M0（首个执行单元）**　日期：2026-10-23
> - 权威依据：`docs/SPEC-20261023-realtime-multimodal-requirements-v1.md`（v1.1，153 条）、`docs/DESIGN-20261023-realtime-multimodal-architecture.md`（v1.2）、`docs/TASKS-20261023-realtime-multimodal-implementation.md`（v1.0）
> - 防退化契约：`docs/DEVELOPMENT_REPAIR_SAFETY.md`（动手前已读，任务执行遵循六问与阶段纪律）
> - 候选指纹：`WORKTREE_HEAD`；设计基线：`main@36a3388e`
> - 状态声明：**M0 未完成**——探针 C 通过，探针 A/B 因缺实时音频 Provider 凭据/设备列为阻断。**未以 mock 冒充完成**（`RTM-EVD-03`）。

---

## 1. 执行摘要

| 探针 | 目标 | 结果 |
| --- | --- | --- |
| C 同会话只读工具 | 隔离 workspace 运行时写校验值 → 真实 `read_file` 回执核对一致 | **通过**（读取值 == 写入值） |
| A 连续听说 | 真实麦克风连续说话 → 归一化事件 + 最终转写 | **阻断**（无实时音频 Provider 凭据） |
| B 本地打断 | 播报中开口 → 立即停播 + `response_id` 中断请求 + 延迟基线 | **阻断**（无实时音频 Provider 凭据/设备） |

结论：M0 的“真实语音链路”可行性**尚无实测依据**，按 `RTM-CAP-07`、`RTM-EVD-03` 显式列阻断；本记录只用于报告，**不得据此宣布 M0 完成**。

---

## 2. 候选冻结与基线核实（T-M0-1）

### 2.1 指纹

| 项 | 值 |
| --- | --- |
| 当前工作树 HEAD | `587eaa2f98d69e01abb802a1443cc4d549b4d43c` |
| 当前分支 | `feat/method-retrieval-idf` |
| 设计基线提交 | `main@36a3388ea195c172a092e956e6224ff41c80306c`（存在、可达） |
| 工作树状态 | 存在未暂存修改（`reports/`、`experiences/`、`scripts/`、`src/llm_loop/eval/verdicts.py` 等）与未跟踪文档；**不计为生产事实** |

> 纪律：不以工作树修改当生产事实；M0 接口事实以**基线提交**为准。

### 2.2 关键文件 SHA-256（基线 `36a3388e`）

| 文件 | SHA-256 |
| --- | --- |
| `src/llm_loop/web/auth.py` | `36be0b36401e25da263261b0894155cbc1fcb1661ec81398106fab6d4d089098` |
| `src/llm_loop/core/loop/runner.py` | `af3f364cb948139fb081334a577e90f7742721c9a508c096c4c5015654383480` |
| `src/llm_loop/web/routes.py` | `a5a194ab1866c1f7af5b4bc6490ea77d450e5219f8b8253af773951d4cfd9a4b` |
| `src/llm_loop/core/tool_execution_journal.py` | `f39d4b5133fe5d62ec09f0dcdee596f4787140ba4ac84c26eb49e3a326f40d44` |
| `src/llm_loop/memory/attachments.py` | `dd7f213256f7cbe463285327b03b8a923976cd82f7de970b348dd2e1ac0364dd` |
| `src/llm_loop/workspace/artifacts.py` | `be8aad3bfa8a17859d7906202894282a337bf56d0382f827debc75fb594f2f5a` |
| `src/llm_loop/tools/registry.py` | `d6b79c636436f8061575b6e6e5a765e657f6a96a77d85cd90dcd95a3ed166e98` |

> `routes.py` 哈希与设计书附录 A 记录一致（`a5a194ab…`），确认基线准确。基线相对当前 HEAD 的差异文件：`src/llm_loop/core/loop/runner.py`、`src/llm_loop/web/routes.py`。

---

## 3. 存量接口只读核实事实（零行为修改）

| # | 位置 | 只读核实事实 |
| --- | --- | --- |
| 1 | `src/llm_loop/web/auth.py` | `WebSessionStore.valid(token)`（:317）；`_bearer_valid(credentials)`（:399）、`_cookie_valid(request)`（:425）合为 `_authenticated`；`validate_origin_allowlist()`（:469）。**鉴权是 HTTP 依赖（`Request`/`HTTPAuthorizationCredentials` 类型）**，WS 不能直接复用 |
| 2 | `src/llm_loop/web/__init__.py` | `_OriginGuardMiddleware`（:79）、`_CanonicalOriginMiddleware`（:127），分别 `add_middleware`（:243/:307）。**仅覆盖 HTTP**，WS 握手不受其保护 |
| 3 | `src/llm_loop/core/loop/runner.py` | `BackgroundRunner.cancel(session_id, *, expected_run_generation=None)`（:527–529）：`expected_run_generation` 比较与取消在同一锁内（:540–552）；`enqueue_interjection(..., expected_run_generation=None)`（:436–441），代次不符拒绝（:453–454）。**精确 `run_generation` 语义已具备** |
| 4 | `src/llm_loop/web/routes.py` | `POST /api/v1/chat/cancel` → `chat_cancel`（:1994–1995）；`artifact_hydrate`（:2029）；`POST /api/v1/chat/queue/interject`（`status_code=202`）→ `queue_interject`（:2155–2156）。路由以 `@router.post` 注册 |
| 5 | `src/llm_loop/core/tool_execution_journal.py` | 状态机 `declared -> started -> finished -> receipt_committed`（模块 docstring :6）；`ToolExecutionJournal`（:192）、`declared()`（:337）、`started()`（:363）**已在记录中携带 `tool_call_id`**。**追加记录 ≠ 原子去重认领**（印证 D4：需新增调用映射/稳定键/原子认领/重启恢复） |
| 6 | `src/llm_loop/memory/attachments.py`、`src/llm_loop/workspace/artifacts.py` | `AttachmentStore`（:112）、`hydrate_text`（:378）；`WorkspaceArtifactStore`（:133）、`read_bytes(ref, *, workspace_scope=...)`（:229）、`hydrate(ref, workspace_scope=...)`（:237）。**授权范围读取与不可变引用已具备** |
| 7 | `src/llm_loop/tools/registry.py`、`src/llm_loop/tools/builtin/read_file.py` | `read_file` 已注册（说明见 registry :68）；`set_exact_read_projection_budget()`（registry :494）与 `_exact_read_projection_budget_chars`（:381）；`ReadFileTool`（read_file.py :51）`execute(**kwargs)`，相对路径基于 `workspace_base()`。**首版只读工具可复用** |

### 3.1 新增落点当前状态（避免循环依赖的前提）

| 路径 | 现状 |
| --- | --- |
| `src/llm_loop/realtime/` | **不存在**（待新增） |
| `webui/src/core/realtime/`、`webui/src/components/conversation/realtime/` | 待新增 |
| `tests/realtime/` | 待新增 |
| Web 层 WebSocket 端点 | **不存在**（Web 目录 WS 端点命中 0；`src/llm_loop` 内 `websockets` 仅用于 CDP/Feishu **客户端**连接，非服务端端点）——WS 属**首次引入**，作为 `T-CONTRACT-4` 前提 |

---

## 4. Provider 能力档案（三态：官方 / 实测 / 未知）

> 因**无实时音频 Provider 凭据**，`T-M0-2`“选定 Provider/传输”**未完成**；下表各项目前**均为未知**，未冻结。

| 能力项 | 官方 | 实测 | 未知 | 阻断说明 |
| --- | --- | --- | --- | --- |
| Provider/模型/API/SDK 版本 | — | — | ✔ | 未选定 |
| 传输（WebRTC / WS 代理） | — | — | ✔ | 未选定 |
| 输入输出音频格式 | — | — | ✔ | 依赖 Provider |
| 最终转写事件 | — | — | ✔ | 依赖 Provider |
| 轮次结束语义 | — | — | ✔ | 依赖 Provider |
| 取消与播放截断能力 | — | — | ✔ | 依赖 Provider |
| 工具调用关联 | — | — | ✔ | 依赖 Provider |
| 图像支持 | — | — | ✔ | 依赖 Provider |
| 恢复方式 | — | — | ✔ | 依赖 Provider |
| 连接限制 | — | — | ✔ | 依赖 Provider |
| 已核实用量字段 | — | — | ✔ | 依赖 Provider 账单 |
| 地区/网络实测条件 | — | — | ✔ | 未实测 |
| 计时口径（客户端单调时钟） | — | — | ✔ | 待 M1 建立 |
| 本地停播基线 | — | — | ✔ | 探针 B 阻断 |
| 长期 Key/令牌仅在服务端 | 设计约定 | — | ✔ | 待实现时核实 |

> **链路等级判定**（对齐 `RTM-CAP-09`）：原生实时与级联（ASR→LLM→TTS）**均不作为预先排除项**，须按连续输入 / 流式输出 / 打断 / 端到端延迟的**实测能力**判定；界面须标明实际采用的链路。当前无实测，故不定级。

---

## 5. 最小探针记录（T-M0-3）

### 5.1 探针 C（同会话只读工具）— 通过

- 方法：隔离脚本（一次性、不进生产路径）以 `tempfile` 建隔离目录，**运行时**写入 `uuid` 校验值 → 实例化真实 `ReadFileTool().execute(path=...)` → 核对回执内容含该写入值。
- 实际命令（内联，未落仓库文件）：`.venv/bin/python - <<'PY'` + 上述逻辑。
- 观测（原始）：
  ```
  PROBE_C_STATUS = success
  PROBE_C_READ_VALUE_FOUND = True
  PROBE_C_CONTENT = '[read_file] .../m0-probe-c-4r1sa7lf/isolated_diag.txt 共 1 行，显示 1-1 行\n1 | probe_written_value=RTM-TOL-09-18536ef9f95e41d3b4915a3dd56198a8\n[symlink] 路径含符号链接: /var'
  PROBE_C_EXIT=0
  ```
- 结论：读取值 == 运行时写入值，**防预置答案冒充**成立（`RTM-TOL-09`）。
- 边界：本探针只经**现有 `read_file` 入口**，**不经桥接**；“提交前不派发、认领后才派发”（`RTM-INP-04`、`RTM-TOL-04`）需在 `T-CONTRACT-2`/`T-M2-3` 落地后验证。

### 5.2 探针 A（连续听说）— 阻断

- 需要：真实实时音频 Provider 凭据 + 浏览器麦克风。
- 现状：环境无 OPENAI/GEMINI/LIVEKIT 等实时音频凭据（仅 DEEPSEEK/KIMI/MINIMAX 文本 key）。
- 结论：未执行，**列阻断**；不得用模拟波形/预录声音代替（`RTM-EVD-03`）。

### 5.3 探针 B（本地打断）— 阻断

- 需要：可播报的实时音频输出 + 麦克风输入 + 客户端停播链路。
- 现状：同上，无实时音频 Provider 凭据与设备。
- 结论：未执行，**列阻断**；本地停播延迟基线（`RTM-PRF-02`）待 M1。

> 三探针**均未**预先构建 `MediaSessionRegistry`/`TurnAggregator`/`TaskBridge`，符合 M0 不循环依赖约束。

---

## 6. 现状基线（对照用）

| 能力 | 现有行为（代码事实） | 延迟/指标 |
| --- | --- | --- |
| 文本流 | 现有 `/api/v1/chat/*` SSE 订阅、队列与 Runner | **未实测** |
| 单次听写 | `DictationButton` 使用 `SpeechRecognition`（`interimResults=false`、`continuous=false`） | **未实测** |
| 图片识别 | `src/llm_loop/web/vision.py` 图转文，独立于核心调用链 | **未实测** |
| 取消 | `chat_cancel` 精确 `run_generation`；SSE 断开只停订阅 | **未实测** |
| 插话 | `queue/interject` 认领队列项并校验精确代次 | **未实测** |

> 延迟类基线无实测数据，按 `RTM-CMP-01`/`RTM-EVD-04` 记为**未完成**，不得以旧历史指标（如 Phase6 模拟窗口）充当语音端到端延迟。

---

## 7. 阻断清单（`RTM-CAP-07`、`RTM-EVD-03`）

1. **无实时音频 Provider 凭据**：探针 A/B 与 `T-M0-2` 能力档案无法实测冻结。
2. **无真实音视频设备链路**：本地停播/首声延迟基线未建立。
3. **Provider 计费单位/用量字段未核实**：`RTM-BUD-01` 计量口径待 `T-CONTRACT-8`。
4. **WS 服务端端点首次引入**：握手鉴权/Origin/归属拒绝路径待 `T-CONTRACT-4`。

> 上述为**显式阻断**，非“无阻断”。在获得实时 Provider 授权与凭据前，M0 的“连续音频→本地打断→只读工具”闭环**不能宣布完成**。

---

## 8. 门禁证据与阶段声明边界

- 已保存证据：候选指纹、关键文件 SHA-256（基线/HEAD）、探针 C 原始命令与退出码（`PROBE_C_EXIT=0`）。
- `T-M0-1` 只读核实：**零行为修改**；核实以 `git grep`/`git show` 读取基线完成。
- 探针 C 脚本为**一次性隔离候选**，未落仓库、未并入生产路径。
- 阶段声明：**未写 PASS**；M0 **未完成**（`RTM-EVD-03`）。M3 完成前不得宣称“实时多模态 MVP 已交付”。

---

## 9. 追溯与后续

- 本记录对应任务：`T-DOC-1`（文档同步核验通过）、`T-M0-1`（完成）、`T-M0-2`（阻断）、`T-M0-3`（C 通过 / A·B 阻断）、`T-M0-4`（本记录）。
- RTM 落位：CAP-05、EVD-03/04、CMP-01、REC-02、AUD-01/03、PLY-02、PRF-02/03/04、INP-04、TOL-04/09。
- 解除阻断前置：取得实时音频 Provider 授权与凭据 → 完成 `T-M0-2` 能力档案三态冻结 → 重跑探针 A/B/C 并留原始记录 → 才能进入 `T-CONTRACT-*` 与 M1。
---

## 10. v1.1 修订（本地栈口径重述，2026-10-23）

> 依据 `docs/TASKS-20261023-realtime-multimodal-implementation.md` **v1.1**（需求 `SPEC` v1.2 163 条 / 设计 `DESIGN` v1.3 本地实时语音栈接线）对 §2–§7 的口径重述。**不改写上文 v1.0 事实**，只追加复核与新证据；结论以本节为最新。

### 10.1 候选指纹复核（T-M0-1，当前工作树）

| 项 | 值 |
| --- | --- |
| 当前工作树 HEAD | `b3181db2d3f3ed534903d2e101e68db54d4f9975` |
| 追踪文件脏改动数 | 27（`reports/`、`experiences/`、`evals/`、`src/llm_loop/eval/verdicts.py`、`tests/test_method_mutator.py` 等） |
| 未跟踪新增 | `docs/*20261023*`、`src/llm_loop/realtime/` 等 |

**关键文件 SHA-256（当前工作树）**：

| 文件 | SHA-256 |
| --- | --- |
| `src/llm_loop/web/auth.py` | `36be0b36401e25da263261b0894155cbc1fcb1661ec81398106fab6d4d089098` |
| `src/llm_loop/core/loop/runner.py` | `790da7411bfa59a97475bb05bc348b2ec64b77ae225e92d08db9e4d71a38b318` |
| `src/llm_loop/web/routes.py` | `7c588b7f47299629b1452b0fe7dc5b0a8b84202094a1ff498a9bc6e5b6bbf315` |
| `src/llm_loop/core/tool_execution_journal.py` | `f39d4b5133fe5d62ec09f0dcdee596f4787140ba4ac84c26eb49e3a326f40d44` |
| `src/llm_loop/memory/attachments.py` | `dd7f213256f7cbe463285327b03b8a923976cd82f7de970b348dd2e1ac0364dd` |
| `src/llm_loop/workspace/artifacts.py` | `be8aad3bfa8a17859d7906202894282a337bf56d0382f827debc75fb594f2f5a` |
| `src/llm_loop/tools/registry.py` | `d6b79c636436f8061575b6e6e5a765e657f6a96a77d85cd90dcd95a3ed166e98` |

> `runner.py`、`routes.py` 相对设计基线 `36a3388e` 已变（对应 v1.0 §2.2 记录的"差异文件"）；其余 5 文件与基线**逐字节一致**。

### 10.2 存量接口只读复核（T-M0-1，当前候选）

- `web/auth.py`：`normalize_origin()`（:118）/`configured_origin_allowlist()`（:156）确为 **HTTP(S) Origin 边界**；鉴权仍为 HTTP 依赖，WS 握手不可直接复用（与 v1.0 §3 一致）。
- `web/routes.py`：`chat_cancel`（:1977）、`artifact_hydrate`（:2011）、`queue_cancel`（:2122）、`queue_interject`（:2138，`enqueue_interjection` 调用 :2207）——行号相对 v1.0 前移，**语义不变**。
- `core/loop/runner.py`：`run_generation` 精确代次（:95 `field(default_factory=uuid)`）+ `enqueue_interjection(expected_run_generation=...)`（:434）。
- `core/tool_execution_journal.py`：`recover()`（:849）——仍为「先读认领、不自动重执行」事实底座。
- `tools/registry.py`：`read_file` 说明（:68）+ `set_exact_read_projection_budget()`（:494）。
- **WS 服务端端点复核**：`src/llm_loop/web/` 内 `websocket`/`realtime` 命中 **0** —— 仓库**仍无 WS 端点**，WS 属首次引入（`T-CONTRACT-4` 前提成立）。

### 10.3 本地栈实测冻结（T-M0-2 v1.1：由"选定远端 Provider"改为"冻结本地栈"）

| 项 | 实测值（本机 2026-10-23） |
| --- | --- |
| Ollama 版本 | **0.20.2** |
| Ollama 端点 | `http://127.0.0.1:11434`；**监听 `TCP *:11434`（IPv6 通配，非仅回环）→ `RTM-SEC-08` 暴露前提待收敛** |
| 已装模型 | `qwen3.5:35b-a3b-q4_K_M`（23.9 GB）、`llama3:latest`（4.7 GB） |
| mlx-audio（ASR/TTS） | **未安装、8010 不可达 → 阻断** |

**CAP-14 运行时/环境约束实测（`.venv`）**：

| 依赖 | 期望 | 实测 | 判定 |
| --- | --- | --- | --- |
| `uvicorn` | 有 | `0.52.4` | ✅ |
| `fastapi` | 有 | `0.141.1` | ✅ |
| `starlette` | 有 | `1.6.0` | ✅ |
| `websockets` | 有 | `15.0.1` | ✅ |
| `numpy` | 有 | `2.5.4` | ✅ |
| `python-multipart` | 有 | **缺失** | ❌ 违反 |
| `webrtcvad` | 有 | **缺失** | ❌ 违反 |
| `mlx-audio` | 有 | **缺失** | ❌ 违反 |
| `sounddevice` | 有 | **缺失** | ❌ 违反 |
| `setuptools` | `<81` | metadata 未注册（需 `pip show` 复核） | ⚠️ 待核实 |

> 结论：**本地栈前提不满足**——`mlx-audio` 未安装，CAP-14 多项依赖缺失。按 §0 纪律 7/`RTM-CAP-14`，`T-M0-2` 记为**部分冻结 + 显式阻断**，**不得宣布通过**。

### 10.4 新增落点状态修订（覆盖 v1.0 §3.1）

| 路径 | v1.0 记录 | 现状（2026-10-23） |
| --- | --- | --- |
| `src/llm_loop/realtime/` | 不存在 | **已存在（未跟踪）**：`__init__.py`（子包声明）、`media_usage.py`（**本轮 `T-CONTRACT-8` 新增**：媒体计量适配层） |
| `webui/src/core/realtime/` | 待新增 | 待新增 |
| `tests/realtime/` | 待新增 | 待新增 |
| Web 层 WebSocket 端点 | 不存在 | **仍不存在**（复核确认） |

> `media_usage.py` 为**本轮 `T-CONTRACT-8` 在建产物**（未提交）；**尚未完成测试门禁**，故暂不计为生产事实。

### 10.5 服务级基线（`OBS-09`）与观察项（`CAP-13`）登记（T-M0-4 v1.1 新增）

- **服务级基线**：`WS ASR → Ollama(think:false) → HTTP TTS`，服务级口径 **12.23 s**；**口径 = 服务级**，**不得**作为 M1/M3 浏览器链路验收值、**不得**与浏览器样本混算（`RTM-OBS-09`）。
- **观察项**：原生全双工 VoiceChat-11B —— `falsification_evidence` / `root_cause_candidates` / `exit_conditions` 已登记，`first_release=false`；证据与复现脚本**不删除**（`RTM-CAP-13`）。
- **浏览器链路**：采集/16k 重采样/播放/VAD/打断**尚未接入**，`AUD/PLY/PRF/SCN/A11Y` 相关条目一律**标未验收**（`RTM-EVD-06`）。

### 10.6 阻断清单修订（v1.1）

1. **浏览器链路接线未完成**（采集/16k 重采样/播放/VAD/打断）。
2. **本地服务暴露/许可待核实**：Ollama 监听 `*:11434`（非仅回环）；`mlx-audio` 许可未核。
3. **`mlx-audio` 未安装**、CAP-14 多项依赖缺失 → 本地转写/TTS 链路前提不满足。
4. **WS 服务端端点首次引入**：握手鉴权/Origin/归属拒绝路径待 `T-CONTRACT-4`。

> 探针 A/B 按 v1.1 重述为**「部分解除：服务级已通、浏览器侧仍阻断」**，**仍不得宣布通过**（`RTM-EVD-06`）。

### 10.7 v1.1 复核结论

| 任务 | 结论 |
| --- | --- |
| `T-DOC-1` | 两处任务清单**正文同步**（`diff` 仅归档多 5 行 SDD 说明段）——**核验通过** |
| `T-M0-1` | 候选指纹、7 文件 SHA-256、存量接口只读复核、无 WS 端点事实——**完成（零行为修改）** |
| `T-M0-2` | Ollama 本地栈实测冻结；`mlx-audio` 与 CAP-14 依赖缺失——**部分冻结 + 阻断** |
| `T-M0-3` | C 通过（依据 v1.0 §5.1）；A/B 部分解除——**未宣布通过** |
| `T-M0-4` | 服务级基线与观察项已登记；阻断清单已按 v1.1 更新 |

> 阶段声明：**M0 仍未完成**；M3 前不得宣称「实时多模态 MVP 已交付」（`RTM-EVD-03/05`）。