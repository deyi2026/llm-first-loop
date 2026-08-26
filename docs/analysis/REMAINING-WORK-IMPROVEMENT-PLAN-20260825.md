# llm-first-loop-mirror 后续未完成任务与改进方案

日期：2026-08-25  
基线 HEAD：`bb2ef6b`  
范围：当前脏工作区在深度审计、主要回归修复完成之后，仍未闭合的交付、工程化、运维与耐久性任务。  
约束：本文只给方案与验收顺序；除本文档外，不修改运行代码、不调整 Git index。

## 1. 执行摘要

当前代码正确性已经比历史 HEAD 明显收敛：此前离线 unit/web/backend/frontend 静态与构建矩阵曾在同一冻结工作区全绿，早期发现的 change-induced regressions 也已逐项修回。现在最大的风险已经从“某个明显功能 bug”转移为三类：

1. **交付状态尚未收口**：当前 index 只有 30 个 staged additions，而 worktree 仍有 125 个 tracked 修改；只提交当前 index 不能代表这次 runtime hardening 的完整实现。
2. **缓存专项仍在 DSH 独立闭环**：breaker / telemetry 分层 / K=3 主骨架已形成，但独立验收仍发现两个行为缺口，长工具会话压力测试不能在它们修复前视为有效验收。
3. **工程门与运维安全仍有缺口**：CI 未跑 WebUI，nightly 未跑真实 cache gate，Release 未构建/安装 wheel，restart 的最终实例验证仍有跨工作区误报/误导人工误杀风险。

建议不要继续扩大功能修改面。正确顺序是：**先等 DSH 缓存专项闭环 → freeze 工作区 → 构造明确的交付候选 → 在候选树上做全矩阵验证 → 再做 CI/Release/运维门加固 → 最后偿还 P2/P3 工程债。**

---

## 2. 当前状态快照

### 2.1 Git / 交付状态

- HEAD：`bb2ef6b`
- staged additions：30 个
  - `src/` 6
  - `tests/` 17
  - `webui/` 2
  - `docs/` 2
  - `scripts/` 2
  - root/other 1
- unstaged tracked 修改：125 个
  - `src/` 66
  - `tests/` 44
  - `webui/` 5
  - `docs/` 5
  - `scripts/` 2
  - root/other 3
- visible untracked：16 个，其中包含 DSH 新增的 `tests/unit/test_cache_breaker.py`，其余大部分属于既知 scratch/manual-review 文件。

因此：**当前 index 不是交付候选树，只是部分新增文件集合。**

### 2.2 已确认必须进入交付的新增 production 模块

以下 6 个 production Python 文件已 staged，且此前已证明 tracked-only 树缺少它们会发生 import/启动问题：

1. `src/llm_loop/core/cache_window.py`
2. `src/llm_loop/core/loop/lifecycle.py`
3. `src/llm_loop/introspection/goal.py`
4. `src/llm_loop/introspection/registry_goal.py`
5. `src/llm_loop/introspection/tools_goal.py`
6. `src/llm_loop/tools/path_registry.py`

这 6 个文件现在“已在 index”并不等于交付已经闭合，因为它们依赖的 66 个生产修改仍主要位于 unstaged worktree。

### 2.3 当前测试证据的正确解读

缓存专项开始前，同一冻结工作区已取得：

- backend unit：全绿
- web tests：全绿
- 除 3 个真实网络 smoke 外的其余 backend tests：全绿
- WebUI：7 files / 52 tests 全绿
- WebUI build：成功，仅有 >500kB chunk warning
- delivery candidate Python Ruff：全绿
- `pyright src`：0 errors / 0 warnings
- `git diff --check`：全绿

但 DSH 之后缓存相关文件继续变化，因此以上结果应视为**最近可信基线**，而不是最终候选提交的最终证明。最终仍必须在 freeze 后重新跑。

---

## 3. P0 / P1：发版前必须闭合

## P0-A. DSH 缓存专项闭环后才能进入最终 freeze

缓存专项由 DSH 主写，本线程不并行改同一批代码。当前已确认：

- `PROGRESSIVE_FOLD_K=3` 已开启。
- `engine.py` 已重新压回既有复杂度预算内。
- breaker/cache monitor/cross-sync focused tests 一度 36 项全绿。
- breaker 主状态机、Rule F 协调、telemetry strip 主体方向正确。

但独立端到端探针发现两个真实缺口：

### P0-A1. breaker pressure 不能按 raw full session 字符数判断

当前实现曾出现：

- full session = 100K chars
- provider anchor 后实际 active tail = 5K chars
- budget = 10K chars
- 95% pressure line = 9.5K chars

真实 active window 明显低于压力线，但 breaker 若用 `sum(sess.messages)` 会按 100K 误判并 BLOCK。

**改进要求：**

- pre-pressure 使用当前 provider/model 对应 anchor 之后、真正会参与构建的 active history 口径；
- build 后 breaker 的退出水位最好直接使用实际 built history/payload 口径，而不是 raw session 存量；
- 测试覆盖“full session 很大但 active anchor tail 很小”场景；
- breaker cooldown / exit hysteresis 必须证明不会形成新的永久 pressure lock。

### P0-A2. telemetry metadata-only 修改必须持久化

独立探针已复现：

- 返回值包含 canonical 缓存遥测；
- 内存 `Message.metadata.cache_health` 已更新；
- assistant content 本来就已经是纯正文；
- `session.save()` 调用数 = 0。

这意味着进程内 Web 返回可能正确，但跨进程/重载后的 Feishu cross-sync 可能丢失权威 telemetry。

**改进要求：**

- 保存判定应是 `content changed OR metadata changed`；
- 测试必须重新 load session 验证 `metadata.cache_health` 仍存在；
- legacy/模型伪造 telemetry 行从 LLM prompt 中剥离；
- transport 只渲染 canonical 一份，不能再次形成内容自污染。

### P0-A3. 长工具会话压测必须在 A1/A2 修复后执行

`tasks/LONG-SESSION-TEST.md` 当前只是一个 9 行长会话记忆夹具，不是压力测试规范。

正式 stress harness 至少应记录：

- 连续工具轮数；
- 每 API round `prompt_tokens/cache_hit/cache_miss`；
- `cache.window` boundary / cached_msgs / new_msgs；
- `context.compressed` 次数；
- anchor movement 次数与最大跳跃；
- breaker enter/pressure/escape/exit；
- tool schema 版本变化；
- 最终回答正确性/工具调用协议错误数；
- 是否出现持续多轮 < 预期命中率的 prefix reset cliff。

压力测试不应只看最终 run-level 平均 hit rate。

---

## P0-B. 构造唯一、可审计的交付候选树

当前 30-file index 不能直接提交。最终交付应建立明确 manifest，而不是 `git add -A`。

### 推荐策略

1. DSH 完成后先记录 freeze：HEAD、status、全部 intended paths、文件 hash。
2. 重建“交付 manifest”：
   - 所有明确属于 runtime hardening 的 tracked 修改；
   - 6 个 required production additions；
   - 与这些行为直接对应的 regression tests；
   - 两个 WebUI regression tests；
   - 必需脚本/正式文档；
   - 明确排除 scratch、临时 benchmark、重复根目录副本、危险 restart_mirror。
3. 只按 manifest stage，不做 blanket `git add -A`。
4. 对 **index/候选树本身** 运行验证，不以 dirty worktree 的结果代替。

### 验收条件

- `git diff --cached --check` 通过；
- security scan 扫 staged blob 通过；
- 候选树能 import 全部新增 production 模块；
- 候选树运行 focused/full offline tests 全绿；
- staged 文件集合与 manifest 精确相等；
- 没有敏感、本地、scratch 文件混入。

---

## P1-A. 恢复可信的 CI 基线

当前 push/PR CI 只做：security → Ruff → Pyright → pytest。

存在两个问题：

1. WebUI 完全不在 CI 中；
2. 当前全 source Ruff 在历史 HEAD 上已存在 15 条错误，11 个文件均属 HEAD_UNMODIFIED baseline debt，因此“全量 Ruff 硬门”与真实基线存在矛盾。

### 推荐改进

短期二选一：

- **优选：一次性清理 15 条历史 Ruff 债务，恢复真正全绿门；**
- 或建立机器可校验的 baseline，只禁止新增错误，并为清零 baseline 建独立任务。

不要长期维持“CI 配置看起来是硬门，但基线天然红”的状态。

### WebUI 新增 CI job

建议：

```text
npm ci
npm test
npm run build
```

前端测试和生产构建都必须成为 push/PR 必跑门。

---

## P1-B. nightly 与本地真实 smoke 必须使用同一验收矩阵

本地 `scripts/run_real_smoke.sh` 已包含：

- `test_real_llm_smoke.py`
- `test_real_llm_exec_smoke.py`
- real tool-call arguments roundtrip
- `test_cache_hit_smoke.py::test_cache_hit_rate_gate`（同前缀真实 cache gate）
- full 模式真实 eval

但 GitHub nightly 只跑前两份 real_llm tests，**遗漏真实 cache gate**。

### 推荐改进

- nightly 尽量复用统一脚本/统一测试清单，而不是维护第二套手写 pytest 列表；
- key 不存在时继续 skip，不误报；
- key 存在时 cache gate 应是 nightly 的显式验收项；
- 对真实 provider 结果单独标注“外部事实验证”，不要与确定性 unit correctness 混为一谈。

---

## P1-C. Release 必须验证真正可安装的 artifact

当前 Release gate 只在源码树执行 Ruff/Pyright/Pytest，随后直接生成 GitHub Release draft。

缺失：

- sdist/wheel build；
- wheel 安装；
- clean env import smoke；
- CLI/Web entrypoint smoke；
- 确认 6 个新增 production 模块确实进入 artifact。

### 推荐流程

1. `python -m build`（或等价 `pip wheel`）；
2. 创建 clean venv；
3. 安装 wheel；
4. 从非 repo cwd 执行 imports；
5. 至少验证 `llm_loop.cli`、`llm_loop.web`、`llm_loop.feishu` import；
6. 读取 wheel 文件列表确认新增模块存在；
7. gate 全绿后才创建 Release draft。

`pyproject.toml` 当前 dev extra 没有 `build`，若采用 `python -m build`，CI 需显式安装。

---

## P1-D. restart_system 的实例验证必须保持镜像隔离

`restart_system.sh` 的停止路径已改为 `PROJECT_DIR/.venv/bin/python -m llm_loop.<svc>` 精确匹配，这是正确方向。

但 `_verify_single_instance` 仍使用泛：

```text
pgrep -f "llm_loop\.<svc>"
```

并在检测多实例后建议人工：

```text
pkill -f 'llm_loop\.<svc>'
```

在主区 + mirror 同机运行时，这会把合法主区实例算成“残留”，并给出可能误杀主区的操作建议。

### 改进要求

- `_verify_single_instance` 必须复用 `_service_pid/_stop_service` 的 PROJECT_DIR 精确匹配口径；
- 自动提示的清理命令也必须限定当前 workspace；
- 增加 restart 脚本测试：同时存在主区和 mirror 模拟进程时，只报告/操作 mirror；
- 不需要扩大自动 kill 权限，原则仍是“只处理可证明属于本项目的 PID”。

---

## 4. P2：发版后尽快偿还的工程债

## P2-A. SessionStore 正常 save 提升到 durable atomic replace

当前 identity/owner/tombstone 写路径已有较强的 `_durable_replace_text`：

- 唯一 tmp 文件；
- flush；
- file fsync；
- `os.replace`；
- best-effort parent directory fsync。

而 `_save_locked` 仍是：

- 固定 `.tmp`；
- `write_text`；
- `replace`；
- replace 失败后直接覆盖正式 JSON。

跨进程锁解决 lost update，但不能提供 crash durability；direct-write fallback 还重新引入半文件窗口。

### 推荐改进

- 正常 session save 复用 durable helper；
- 不再用 direct-write 作为原子写失败后的默认 fallback；
- 无法安全 replace 时走现有 recovery/backup 通道并明确报错/告警；
- 增加 fault-injection：write/fsync/replace/dir-fsync 各阶段异常；
- 验证失败后旧正式文件仍可读，且不会留下被误读的半 JSON。

共享 `current_session` 文件也建议采用同一基础设施，并至少把当前静默 `pass` 改成降级日志。

---

## P2-B. 明确定义 physical delete 的数据 retention policy

当前物理删除会清：

- Archive；
- session recovery backup；
- feedback sidecar；
- full-session-id long-answer sidecar。

但 Memory、Evolution、Audit、metrics 等派生记录没有一个统一“随会话删除”的产品语义。

这不应由代码层自行猜测。

### 先定义策略表

对每类数据明确：

- ownership：session-scoped / workspace-scoped / global；
- 是否包含用户内容；
- physical delete 是否同步删除；
- 是否保留匿名聚合；
- retention TTL；
- 是否受审计/合规要求约束；
- 删除失败时是否阻断主删除。

策略确定后再实现统一 purge coordinator，避免各 sidecar 在 factory 中继续散落增长。

---

## P2-C. git_security_scan 的 staged/tree 口径改成真正 Git 对象口径

当前工具总体有效，敏感路径、密钥、绝对路径、大文件规则齐全，Surge 凭据文件也已明确 gitignore。

但有两个工具语义小缺口：

- `--staged` 内容读 index blob，但大文件 size 读 worktree 文件；若 staged 后又改 worktree，两个判断对象不同；
- `--tree` 本地执行时文件内容来自当前 worktree，不是真正 Git tree blob；dirty tree 下名称与语义不一致。

### 推荐改进

- staged 模式的 size/content 都从 `git show :path` / index blob 取得；
- tree 模式明确指定 `HEAD:path` 或传入 tree-ish；
- CI clean checkout 仍保留，但工具本身也应具有确定性；
- 加一个“staged 与 worktree 内容不同”的 regression test。

---

## P2-D. WebUI chunk 与 warning 治理

此前生产 build 成功，但主 JS chunk 约 542.8kB，Vite 仅给 >500k warning。

当前 `vite.config.ts` 没有 manualChunks/lazy chunk 设计。

### 推荐改进

优先做低风险拆分：

- KaTeX / markdown parser；
- sidebar evolution / 重型面板；
- 非首屏功能 lazy import；
- 视情况拆 React vendor。

目标不是为了“消灭 warning”硬拆，而是：

- 首屏主 chunk 明显下降；
- 流式聊天核心路径不被额外 async waterfall 拖慢；
- build 输出增加 size budget，并在 CI 中只对显著回归失败。

---

## P2-E. fail-open 可观测性继续统一

审计过程中已确认本轮没有新增 TODO/FIXME 实现空洞；changed src 中扫描到的 silent-pass 均是 HEAD baseline 或未修改上下文，不应误算本轮回归。

但仍有两处较值得优先清理的 observability debt：

- `edit_file.py`：编辑成功后 path registry 登记异常可静默；
- `path_registry._normalize_path`：workspace_base 解析异常静默 fallback cwd。

这类辅助机制可以 fail-open，但至少应 debug/warning + 可检索 fault metric，避免路径登记/归属异常完全不可见。

---

## 5. P3：低风险清理项

1. restart/status 中只做 JSON 解析的 system `python3` 统一成项目 `.venv/bin/python`，减少环境漂移。
2. 清理 15 条已证明属于纯 HEAD baseline 的 Ruff 风格债务；如果 P1 阶段已一次清零，本项自动完成。
3. 对测试中的 React `act(...)` warnings 做单独清理，不把 warning 当 correctness failure。
4. root 下重复 `cache_window.md`、`local_cache_probe.py`、`client.py`、`test_llm_client.py` 等 scratch 继续保持不入库；最终交付后统一清理工作区，避免下一轮误判来源。
5. 两份分析类文档（例如 cache optimization report / map-retrieve-consume design）独立做资产评审，不与 runtime commit 强绑定。

---

## 6. 推荐执行顺序

### Phase 0 — DSH 缓存专项完成

只完成缓存闭环，不同时扩其它工程修改：

1. breaker active-window 口径；
2. telemetry metadata durability；
3. 两条新增 Ruff；
4. focused/unit；
5. 长工具会话 stress；
6. 再评估 tool result / memory，而不是提前重构。

### Phase 1 — Freeze + Delivery Manifest

1. 记录 HEAD/status/hash；
2. 重新枚举 tracked modified + required untracked；
3. 按行为能力确认 regression tests，不机械恢复旧文件名；
4. 排除 scratch/manual/dangerous scripts；
5. 经人工授权后才 stage。

### Phase 2 — Candidate-tree Offline Gates

必须在“拟提交树”而不是当前 dirty worktree 上验证：

1. import smoke；
2. cache focused tests；
3. concurrency / session lease / workspace / identity / event bus focused tests；
4. backend full unit；
5. web tests；
6. WebUI `npm ci && npm test && npm run build`；
7. delivery Ruff；
8. Pyright；
9. `git diff --cached --check`；
10. staged security scan。

### Phase 3 — Package / Release Artifact Gates

1. build sdist + wheel；
2. clean venv 安装 wheel；
3. 非 repo cwd import/CLI/Web smoke；
4. 验证新增 6 production modules 都进入 wheel；
5. 再允许打 tag / Release draft。

### Phase 4 — Real Provider Gates

在明确接受外部请求成本后：

1. real_llm protocol smoke；
2. real tool-call roundtrip；
3.真实 prefix cache gate；
4. 必要时完整 eval。

这些结果用于验证 provider/live-model 事实，不反向否定已全绿的确定性代码状态机。

### Phase 5 — Operational Rollout

1. 修正 restart single-instance workspace scope；
2. 优雅 restart；
3. Web `/health`；
4. Feishu heartbeat；
5. 单 workspace 单实例检查；
6. 短真实对话 + 工具调用 + cross-sync；
7. 观察 event log / breaker / cache telemetry 是否出现异常。

### Phase 6 — Post-release Engineering Debt

依次处理：

1. SessionStore durability；
2. retention/purge policy；
3. CI/Release pipeline hardening；
4. security-scan Git-object semantics；
5. WebUI chunk；
6. observability + historical Ruff/warnings。

---

## 7. 最终“可发布”定义

只有同时满足以下条件，才建议把当前审计目标视为真正进入交付完成态：

- DSH 缓存专项两个端到端缺口闭合；
- 长工具会话 stress 没有 compression storm / breaker deadlock / telemetry self-pollution；
- intended production + tests + scripts/docs 已形成精确 manifest；
- 候选 index 没有 scratch/凭据/本地文件；
- offline backend/web/frontend/static/build 全绿；
- wheel/sdist 可构建、clean-install 可 import；
- scripts executable / restart workspace isolation 通过；
- 真实 provider smoke 的执行/跳过状态有明确记录；
- 最终 `git diff --cached` 可独立解释，不依赖未提交 worktree 才能运行。

在这之前，不建议把“当前工作区能跑”视为“当前提交可交付”。

---

## 8. 不建议现在做的事情

- 不要在 DSH 正改缓存路径时并行重构 memory/tool result。
- 不要通过单纯降低 DeepSeek history budget 代替 breaker 根因修复。
- 不要只为恢复旧测试文件名而复制已经被现有测试覆盖的测试。
- 不要 `git add -A`。
- 不要把真实网络 smoke 未执行表述成代码失败。
- 不要在 retention policy 未定义前擅自级联删除 Memory/Evolution/Audit。
- 不要为了消除 Vite warning 优先改大块前端架构；它不是当前发版 correctness blocker。
- 不要使用泛 `pkill -f llm_loop...` 清 mirror 实例。

## 9. 建议的下一动作

当前最合适的下一动作不是继续改非缓存代码，而是：

1. 把本文作为后续 backlog / release checklist；
2. 等 DSH 回报 A1/A2 修复及 focused/unit/stress 结果；
3. 立即重新 freeze Git 状态；
4. 按 Phase 1 构造唯一 delivery manifest；
5. 经明确授权后，再进入 stage/candidate-tree 验证阶段。

