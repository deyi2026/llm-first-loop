# 编排效率加固 需求与实现设计书 v1

**文档 ID**: `DESIGN-20261101-efficiency-hardening-v1`
**类型**: design（需求 + 实现设计）
**日期**: 2026-11-01
**状态**: 设计稿，**未实施**；含 4 个待裁决点（§10）
**上游**: `GOAL-20261101-29f09541` 交付复盘中提出的 5 项效率发现；拷问记录见 §7
**适用规则**: RULE-AI-00 / 01 / 07 / 08 / 18 / 23 / 24；实施前按 RULE-AI-28 过独立审查

> **事实基线**：本文所有"已核"结论均来自 2026-11-01 11:00 前后对工作区 `llm-first-loop-mirror`（HEAD `32f3310a0`，干净树）的实测；未复核项在 §2.2 单列，不并入结论。凡未核项，本文不据其做判断。

---

## 0. 结论摘要

1. **5 项发现按性质分三类，不该一律叫"效率优化"**：真缺陷 2 项（E1 破坏性搬迁、E3 终态不可归因）；自证缺失 2 项（E2 模型来源、E4 解释器不自证）；流程债 1 项（E5 契约漂移）。分类决定验收口径不同——缺陷看"是否还会发生"，自证看"30 秒内能否看出异常"。

2. **E1 不是效率问题，是数据完整性问题**：共享工作树被外部管线整体搬迁，恢复凭据只存在于 `/tmp` 目录内容里，既不在回执也不在事件流。优先级最高，且**我无法在本仓库内关闭它**——实现不在本仓库代码面（F3），本设计只能做"可恢复 + 可感知"，根治要改交付管线。

3. **拷问推翻了我上一轮 3 条建议中的 3 条**（§7.2）：`optional_dep` 标记是错根因（真因是解释器选错，F10/F11）；"回执不回显模型"是假（回显有，F5）；"父会话拿不到任何摘要"过强（有摘要，缺归因，F6）。这三条若直接进实现，会做出无用甚至有害的东西。

4. **最优性价比改动是 E4**：一个 conftest 预检（约 40 行）即可把"107 个 collection error"变成"一条可执行诊断"，把全量测试从"常年红灯"恢复成有回归意义的信号。零产品风险。

5. **E2/E3 都是回执字段级改动**（各 3–5 行），但需要一处数据源决策：`files_written` 在跨进程 child 上不可得时，**允许报 `unavailable` 而不是空列表**——宁可承认不知道，也不伪报"没写过"。

6. **E5 不是写个生成器就完**：契约表有两个腐化方向（文档腐化、代码腐化），必须锁定"文档为源、代码为被检对象"，否则只是把漂移换了个位置。

7. **本轮无代码改动**。本文档是唯一交付物；上一轮 L1–L4 的改动仍未提交，现存于 `git stash` 与 `/tmp` 备份（F15），是否恢复需用户单独决定（§10 D4）。

---

## 1. 需求与可验收分解

### 1.1 原始诉求（逐条溯源）

| # | 上一轮原话（摘要） | 性质 | 处置 |
|---|---|---|---|
| E1 | 自动 push 管线在运行中搬迁工作树，两次把未提交改动整体移出工作树，不输出恢复指令、不登记事件 | 缺陷 | §4.1 保留并强化 |
| E2 | spawn 不指定 model 时静默继承父会话模型，回执没有回显来源 | 自证 | §4.2 收窄为"缺 source 标记" |
| E3 | 子代理无产出静默消失，父会话拿不到"改了什么/停在哪" | 缺陷（弱化） | §4.3 重定义为"终态不可归因" |
| E4 | 缺 `Crypto`/`lark_oapi`/`reportlab`/`prompt_toolkit` 让数百项常年失败，建议打 `optional_dep` 标记 | 自证（原建议错根因） | §4.4 完全重写 |
| E5 | 设计→实现仍存在命名/落点漂移，建议固定契约表 + 生成契约测试 | 流程债 | §4.5 保留并加反腐化约束 |

### 1.2 可验收需求（R 表）

每条都是**可执行断言**，不是描述。验收方式见 §9。

| ID | 需求 | 可执行断言 | 优先级 |
|---|---|---|---|
| R1 | 工作树搬迁必须自带恢复凭据 | 任一次搬迁后存在机器可读 `LATEST.json`，含 `restore_cmds`（≥3 条可执行命令）、`file_counts`、`sha256`，可被脚本消费 | P0 |
| R2 | 搬迁必须可感知 | 搬迁动作产生 workspace 事件 `git_worktree_relocated`，`event_stream(scope=workspace)` 可检索，字段含 `actor`/`stash_ref`/`backup_dir` | P0 |
| R3 | 非静默工作区不得被搬迁 | 近 10 分钟有未提交变更或 mtime 更新 → 拒绝搬迁，`reason_code=workspace_busy`；仅显式 `--allow-dirty`（人授权）可越过 | P0 |
| R4 | 模型能自诊"文件怎么突然变干净了" | 只读工具 `workspace_recovery_status` 一次调用给出：脏文件数、最近搬迁时间、备份目录、可直接执行的恢复命令 | P0 |
| R5 | 测试运行必须自证解释器与依赖 | 缺依赖时 pytest 以**单条**诊断退出，含解释器路径/版本、缺失模块、修复命令；不产生任何 collection error | P0 |
| R6 | 测试结果带环境指纹 | 报告头/junit 属性含 `sys.executable`、`python_version`、依赖版本摘要 | P1 |
| R7 | 子代理模型来源可见 | `spawn_subagent` 回执含 `model_source ∈ {specified, inherit_default, legacy_default}`；`inherit_default` 附一行提示 | P1 |
| R8 | 子代理终态可归因 | `subagent_result` 终态回执含 `terminal_reason ∈ {completed, failed, parent_stop, truncated_rounds, lease_lost, error, orphan_reaped}`（枚举依据 F16 实测，非凭经验拟定） | P1 |
| R9 | 子代理轨迹覆盖尾部 | 工具轨迹改 `head-3 + tail-7`，长任务能看到真正失败点 | P1 |
| R10 | 子代理写入面可见 | child 声明 `write_scope` 时回执含 `files_written`；不可得时报 `unavailable`，**不得为空列表** | P1 |
| R11 | 停滞可见但不自动杀 | 超阈值无活动 → 事件 `subagent_stalled` + 父回执一行提示；**不终止** child | P2 |
| R12 | 设计契约可被 CI 校验 | 文档内 `yaml contract` 块可被 `scripts/gen_contract_tests.py` 解析生成测试；文档与代码 registry 不一致时 CI 失败并定位条目 | P2 |

### 1.3 边界澄清（明确不做）

- **不做自动恢复**：搬迁后自动恢复会让管线和会话抢同一个工作树，冲突不可判。恢复必须显式执行（R4 只给命令，不执行）。
- **不做常驻守护进程**：检测走现有事件流 + 只读查询，不新增后台线程。
- **不改变子代理取消语义**：R11 只加观测，不引入自动 kill——杀掉会丢可救的半成品，而 `agent_message` 已提供中途纠偏。
- **不重写推送管线**：见 §10 D1；本仓库侧严格限定"可恢复 + 可感知"。
- **不以"更快"为唯一理由**加任何改动。

---

## 2. 现状核实

### 2.1 已核事实（F1–F15）

| ID | 事实 | 证据位置 |
|---|---|---|
| F1 | `git stash list` 有 3 条 2026-11-01 搬迁记录：`pre-push-20261101: 29 tracked + 112 untracked`、`pre-push-2-…: runtime artifacts`、`pre-push-3-…: non-runtime in-flight` | `git stash list` 回执 |
| F2 | `/tmp/lfl-prebackup{2,3}-<ts>/` 与 `/tmp/lfl-prebackup-LATEST.txt` 存在；目录含 `status.txt` / `tracked.patch` / `untracked.list.z` / `untracked.tgz` / `SHA256SUMS` | 备份目录清单 |
| F3 | **本仓库内不存在该管线实现**：全仓检索 `prebackup`（scripts/src/tools/pyproject）无命中；`.git/hooks/` 仅 `*.sample`；`crontab -l` 无相关项；`~/Library/LaunchAgents` 无匹配 plist | 检索回执 |
| F4 | 备份产物**无恢复指令**：`status.txt` 是搬迁时刻的 `git status` 快照，`tracked.patch` 是裸 diff，`LATEST.txt` 只是目录路径 | 阅读备份文件 |
| F5 | 模型解析：`requested_model = model or ""`；`inherited_model = current_model_label.get()`；`child_model_ref = requested_model or inherited_model`；回执已输出 `model=<resolved>` | `subagent/runner.py:1617-1623`、`tools/builtin/spawn_subagent.py:385` |
| F6 | `subagent_result` 终态回执字段为 state/outcome/depth/rounds/tools/tokens 等；轨迹取 `[:10]`；无 `terminal_reason` / `files_written` / `last_activity` | `tools/builtin/subagent_result.py:108`、`:128`、`:155` |
| F7 | `subagent/` 与 `fleet/` 中 `watchdog` / `stalled` / `idle_timeout` 命中数 = 0 | 检索回执（计数值 0） |
| F8 | lease 已有 `expires_at` 与 rolling-TTL 心跳 | `fleet/store.py:87`、`:381` |
| F9 | 依赖声明：`lark-oapi>=1.7.2`(13)、`pycryptodome>=3.23`(15)、`prompt-toolkit>=3.0.52`(18) 属**必装**；`reportlab>=4.0`(35) 属 dev extra | `pyproject.toml` |
| F10 | 系统 `python3` = 3.14.6，四依赖全缺；仓库 `.venv/bin/python` = 3.13.13，四依赖齐备 | 两解释器 import 实测 |
| F11 | **同一命令、仅换解释器**：系统解释器收集 → 11648 collected + **107 errors**（Crypto×100 / lark_oapi×3 / reportlab×1 / prompt_toolkit×1）；`.venv` → **13147 collected / 0 error**（16 deselected） | 两次收集实测 |
| F12 | CI 入口已绑定 `.venv`：`PY="${PY:-$ROOT/.venv/bin/python}"` | `scripts/ci_gate.sh:29` |
| F13 | pytest 配置：`addopts` 含 `--import-mode=importlib -m "not real_llm"`；markers 已声明 | `pyproject.toml:76`、`:81` |
| F14 | 上一轮设计 §12.2 登记 9 条实现偏差（D-impl-1..9），其中 4 条为命名/落点/初值漂移 | `DESIGN-20261101-cross-session-coordination-v1.md` §12.2 |
| F15 | 上一轮 L1–L4 改动未提交：`/tmp/lfl-prebackup3-20261101-104015/tracked.patch` 含目标文件 diff，`/tmp/lfl-xsession-backup/` 含全量副本（docs/src/tests） | 目录清单 |
| F16 | 子代理终态面实测：`outcome` 枚举 = `completed/failed/cancelled/truncated/refused`（`runner.py:213`）；`cancel_reason` 在唯一写入点硬编码 `parent_lifecycle_cancel`（`core/subagent_delivery.py:449-459`）；`tool_trace` 只记 `name:status` 无路径（`runner.py:3464`）；lease 无 `last_activity` 字段（`fleet/store.py:77-87`） | `work/efficiency-audit/E2-subagent-observability.md`（子代理 glm-5.3 独立调查产出，本文 §4.3 据此修订） |

### 2.2 未核 / 作废（不并入结论）

| ID | 内容 | 处置 |
|---|---|---|
| U1 | 上一轮"9076 passed / 311 failed / 33 collection error" | 与 F11 实测（107 errors）口径不一致，**不作基线**；成因未查（疑统计被中断）。§9 不引用 |
| U2 | "第一次搬迁删掉 12 个文件" | 上一轮现场观察，本次未复核；仅作动机说明 |
| U3 | 搬迁管线的实现、触发条件、可配置性 | 未定位（F3），属交付管线一侧；§4.1 方案据此只承诺本仓库侧 |
| U4 | D-impl-1..9 是否全部仍成立 | 未逐条回归，仅按文档记录引用 |

### 2.3 由事实直接推出的三条判断

- **J1**：E4 的根因不是"依赖可选性设计"，而是**执行入口未被约束**——F9/F10/F12 同时成立（依赖是必装、venv 完备、CI 已绑定 `.venv`），唯独"手敲命令"这条路没有自证。
- **J2**：E2 的问题不是"看不见模型"，而是**看不见"这个模型是谁定的"**（F5 三条来源分支只回显结果，不回显分支）。
- **J3**：E3 的问题不是"没有摘要"，而是**摘要截断在头部 + 缺归因字段**（F6 的 `[:10]`）。

---

## 3. 差距与设计约束

### 3.1 差距表

| 需求 | 现状 | 差距类型 | 关闭成本 |
|---|---|---|---|
| R1/R2 可恢复可感知 | 备份目录存在但无机器可读恢复凭据、无事件（F2/F4） | 缺实现 | 低（脚本 + 事件一行） |
| R3 静默门 | 无任何前置判定（F3：实现不在本仓库，无法验证其是否判过） | 缺实现 + 属外部 | 中（需管线侧配合） |
| R4 自诊 | 无只读入口；模型只能翻 `/tmp` | 缺工具 | 低–中（1 个只读工具） |
| R5/R6 环境自证 | 入口已绑定 `.venv`（F12），但手敲命令无提示（F10/F11） | 缺守卫 | 低（conftest 预检 ~40 行） |
| R7 模型来源 | 只回显结果（F5） | 缺字段 | 极低（3 行） |
| R8/R9/R10 终态归因 | 有摘要但截断在头部、无归因字段（F6） | 缺字段 + 采样偏差 | 低（5 行 + tail 采样） |
| R11 停滞观测 | 全无（F7） | 缺实现 | 中（依赖 F8 心跳源） |
| R12 契约校验 | 漂移靠人工登记（F14） | 缺机制 | 中（生成器 + CI 门） |

### 3.2 设计约束

- **C1 不新增阻塞面**：所有新检查在"缺失/异常"时要么给一条诊断，要么降级为 `unavailable`，不得让原本能跑的场景跑不起来。
- **C2 不替模型做语义裁决**：程序只暴露事实（模型是谁定的、谁写的文件、缺什么依赖），不判断"这模型够不够聪明""这次测试算不算绿"。
- **C3 破坏性动作必须由人授权**：`--allow-dirty` 一类越过静默门的开关，模型侧不可得（工具白名单硬编码）。
- **C4 承认不可知**：跨进程 child 的写入面、无心跳源的停滞时长，一律报 `unavailable`，禁止用空列表/0 冒充"没有"。
- **C5 单一事实源**：解释器以仓库 `.venv` 为准，契约以文档 `yaml contract` 块为准——不在两边各留一份。

---

## 4. 方案设计

### 4.1 E1 工作树搬迁：可恢复 + 可感知（P0）

**事实**：F1–F4。搬迁 3 次，产物是原始材料（patch/tgz），没有"怎么做"。

**根因（三条，前两条是设计缺陷，第三条是可见性缺陷）**

1. 搬迁者把"树干净"当唯一目标，把"脏树"当可丢弃中间态——它优化的是管线自身的可推送性，代价转移给会话。
2. 恢复凭据只有**原材料**（patch、tgz），缺少**可执行步骤**（`restore_cmds`）。恢复因此要求执行者既懂 git/tar，又要自己判断"哪些文件该回、冲突怎么办"。
3. 无事件 → 文件突然消失时，模型的第一假设是"我记错了/我删了"，而不是"被搬走了"。上一轮我确实是靠翻 `/tmp` 才自证的。

**设计**

- **S1-a 恢复凭据结构化**：`LATEST.json`（带 `schema_version`），字段：`created_at` / `actor` / `stash_ref` / `stash_sha` / `backup_dir` / `file_counts{tracked,untracked}` / `restore_cmds[]` / `verify_cmd` / `patch_sha256`。人读 `LATEST.md`（同内容渲染）可选。
- **S1-b 三档恢复命令**：只读检查 → 试应用 → 正式应用，避免"一步到位"的不可逆操作。
- **S1-c 事件登记**：`git_worktree_relocated`，字段见 §5 契约 C-E1-02。
- **S1-d 静默门（quiescence）**：判据 = 近 T 分钟（默认 10）内存在未提交变更 / index 变更 / HEAD 变动。判定不静默 → 拒绝搬迁，返回 `reason_code=workspace_busy` + `earliest_retry_at`（不是"无限等待"，是"给出最早可重试时刻"）。
- **S1-e 只读自诊工具** `workspace_recovery_status`：输出当前脏文件数、最近搬迁时间、备份目录、恢复命令，以及"当前 HEAD 是否就是搬迁前 HEAD"。

**恢复命令块（S1-b 的产出格式）**

```json
{
  "schema_version": 1,
  "created_at": "2026-11-01T10:40:15+08:00",
  "actor": "pre-push-pipeline",
  "stash_ref": "stash@{0}",
  "stash_sha": "5b1c9e7",
  "backup_dir": "/tmp/lfl-prebackup3-20261101-104015",
  "file_counts": {"tracked": 5, "untracked": 2},
  "patch_sha256": "<64 hex>",
  "restore_cmds": [
    "T1 只读检查  | git apply --check <backup_dir>/tracked.patch",
    "T2 正式应用  | git apply <backup_dir>/tracked.patch   (或以 stash_ref 为准)",
    "T3 未跟踪文件 | tar -xkf <backup_dir>/untracked.tgz -C .   (冲突则写 <backup_dir>/restored/)"
  ],
  "verify_cmd": "git status --short",
  "tiers": {"T1": "只读", "T2": "可逆（失败即中止）", "T3": "需冲突检查"}
}
```

> 设计要点：`restore_cmds` 不是"裸命令字符串数组"，而是带 `T1/T2/T3` 分档的结构——恢复者必须先跑只读档，再决定是否进 T2。原备份只给了 T2 的**材料**（patch），没给 T3 的**方法**，这是上一轮我只能手工翻目录的直接原因。

**落点**

| 改动 | 位置 | 归属 |
|---|---|---|
| `LATEST.json` 生成 + 静默门 + `--allow-dirty` | 交付管线侧（**不在本仓库**，F3） | 需外部配合 |
| `scripts/restore_prebackup.sh`（消费 `LATEST.json`，幂等、可 `--check`） | 本仓库新增 | P0 可独立落地 |
| `workspace_recovery_status` 只读工具 | `src/llm_loop/tools/builtin/` | P0 |
| 事件 `git_worktree_relocated` | 若管线不可改：由恢复脚本首次被调用时补登 `retro=true` | 降级方案 |

**失败模式**

| ID | 场景 | 处置 |
|---|---|---|
| M1 | 恢复时工作区又变了 → 冲突 | 先 `--check`；冲突不覆盖，落到 `<backup_dir>/restored/` 并列出冲突文件 |
| M2 | untracked 解包覆盖同名新文件 | 解包前比对同名文件 sha256，不同则写 `restored/` |
| M3 | 静默门导致推送永久阻塞 | 给出 `earliest_retry_at` + 超窗后仍需**人**显式 `--allow-dirty`；不自动放行 |
| M4 | `/tmp` 被系统清理 → 备份失效 | 搬迁后 24h 内把 `LATEST.json`+`patch` 复制到 `.git/lfl-prebackup/`（不进工作树、不可提交），保证重启后可恢复 |

> M4 是本次新增的：**备份放在 `/tmp` 本身就不满足 R1**——"可恢复"要求恢复凭据的存活期长于系统临时目录的清理周期。

### 4.2 E2 子代理模型来源透明（P1）

**事实**：F5。三条来源分支（显式指定 / 继承父会话 / 全局默认）在回执里坍缩成同一个 `model=` 值。

**根因**：不是"看不见模型"，而是**看不见"这个模型是谁定的"**。这是决策权归属缺失，不是信息缺失——同一个值，可能意味着"我选了 glm-5.3"，也可能意味着"我没写参数，系统给了我父会话那个快模型"。

**设计**

- 回执追加 `model_source ∈ {specified, inherit_default, legacy_default}`。
- `inherit_default` 时追加**单行**提示：`[提示] 未显式指定 model，已继承父会话模型 <X>；如需指定请传 model 参数`。
- 回执追加 `parent_model_at_spawn`：spawn 时刻父会话模型快照（用 contextvar 读一次，不追踪后续变更）。
- `legacy_default` 单独一档：`requested` 与 `inherited` 都为空（无父 contextvar，例如 CLI 直起）时走全局默认，必须标出来——它最容易被误当作"继承"。

**落点**

| 改动 | 位置 | 影响面 |
|---|---|---|
| `child_model_label` 旁并列记录来源分支 | `subagent/runner.py:1617-1623` | 只加变量，不改解析顺序 |
| started/回执行追加两字段 | `subagent/runner.py:~1958`、`tools/builtin/spawn_subagent.py:385` | 回执纯增量 |

**失败模式**

| ID | 场景 | 处置 |
|---|---|---|
| M5 | 提示行抬高回执噪声 | 仅在 `inherit_default` 出现，且限单行 |
| M6 | 父会话中途 `switch_model`，child 仍用 spawn 时刻模型 → 被误判成 bug | `parent_model_at_spawn` 显式记录快照语义；文档写明"child 不跟随父模型变更" |

> 取舍说明：**不**在继承时自动提高模型档位。程序无权判定"这个任务值不值得用贵模型"，只能告警。

### 4.3 E3 子代理终态可归因（P1）

**事实**：F6/F7/F8/F16。终态有摘要，但轨迹 `[:10]` 截在头部、无归因字段、无最后活动时间。

**根因（四条；第 1、3、4 条已由 F16 从"推测"升级为"实测"）**

1. **来源坍缩**：存储层 `outcome` 枚举是 `completed | failed | cancelled | truncated | refused`（`runner.py:213`），而取消路径的 `cancel_reason` 在**唯一写入点**被硬编码为 `parent_lifecycle_cancel`（`core/subagent_delivery.py:449-459`）→ 父 Stop、外部 cancel、reaper 回收三者**在数据层就无法区分**。
2. **采样偏差**：`[:10]` 在长任务上必然看不到失败点——失败通常发生在尾部。
3. **轨迹不含路径**：`tool_trace` 只记 `name:status`（`runner.py:3464`），没有文件路径也没有参数 → 即使拿到轨迹，也回答不了"它改了什么"。
4. **无时间锚**：lease 只有 `expires_at`（`fleet/store.py:77-87`），没有 `last_activity` 字段；唯一可推导量是 `expires_at − ttl`，且粒度是"轮边界"。

**设计**

- **S3-a `terminal_reason`**：由 `outcome` + `cancel_reason` + 租约状态映射，取值 `completed | failed | parent_stop | truncated_rounds | lease_lost | error | orphan_reaped`。**刻意不用裸 `timeout`**：当前系统没有 wall-clock 超时，只有启动握手 2s（`runner.py:1936-1944`）、轮数上限（`:3529-3543`）、租约 TTL 三种；混称 timeout 会把"轮数截断"和"权威失效"错误归因到同一个原因。
- **S3-a′ `cancel_origin` 参数化**：把 `subagent_delivery.py:449-459` 的常量 reason 改成入参，取值 `parent_stop | external_cancel | reaper`。这是 M7 的真正解法——不改这一处，回执再丰富也只能报"被取消了"。
- **S3-b 轨迹采样改 `head-3 + tail-7`**：头部覆盖"一开始就没进入状态"，尾部覆盖"死在最后一步"。
- **S3-c `files_written`**：数据源**不是** `tool_trace`（无路径，见根因 3），而是 `tool.execution.effect_prepared` / `effect_observed` 事件与 journal sidecar；仅当 child 声明 `write_scope` 时产出，跨进程 child 报 `unavailable`。
- **S3-d `last_activity_at` / `stalled_for_s`**：由 `expires_at − ttl` 推导并标 `derived=true`；推导不出则 `unavailable`（不得报 0）。
- **S3-e（P2）`subagent_stalled` 事件**：超阈值仅告警，不终止（见 §1.3）。

**失败模式**

| ID | 场景 | 处置 |
|---|---|---|
| M7 | 父 Stop 与手动取消都落成同一 reason → 全被误判 `parent_stop` | **已核实为事实**（`cancel_reason` 是常量，F16）；处置 = S3-a′ 参数化，而非"新增判断逻辑" |
| M8 | `files_written` 可能含"打开但未成功写入"的文件 | 只统计写类工具的成功回执，失败调用单列 `write_attempts_failed` |
| M9 | tail 采样把早期信号挤掉 | 保留 `head-3`；`head+tail` 总数固定 10，不随任务变长而膨胀 |
| M15 | 用 `expires_at` 反推活动时间，在"单轮跑很久"时严重低估活动 | 标注 `derived=true` + 同时给 `expires_at` 原值，让消费者自己判断可信度 |

### 4.4 E4 测试环境自证（P0，原建议已被推翻重写）

**原建议及其错误**

原建议是"给缺依赖的用例打 `optional_dep` 标记，默认 `-m 'not optional_dep'`"。它假设这些依赖是**可选**的。实测推翻了这个假设：

- F9：`lark-oapi` / `pycryptodome` / `prompt-toolkit` 都写在 `[project.dependencies]`（**必装**），只有 `reportlab` 在 dev extra；
- F10/F11：同一份代码、同一条命令，**只换解释器**，collection error 从 107 → 0，收集数从 11648 → 13147；
- F12：CI 入口本来就绑定 `.venv`。

→ 真正的缺陷是"**绕过入口时系统不吭声**"，不是"依赖需要分层"。按原建议实现，会把必装依赖打上"可选"标记，等于把一次环境故障永久合法化——比不做更糟。

**设计**

- **S4-a conftest 预检**（在收集任何测试前执行）：用 `importlib.util.find_spec` 检查必装依赖 + 比对解释器是否指向仓库 `.venv`。缺**必装依赖** → 单条诊断退出；解释器不是 `.venv` 但依赖齐全 → 仅 warning（不拦人做单文件调试）。
- **S4-b 环境指纹**：报告头与 junit 属性写入解释器路径、版本、依赖版本摘要，使"这次结果在哪个环境跑的"事后可追溯。
- **S4-c dev-only 依赖**（`reportlab`）走 `importorskip`，只跳过相关用例。
- **S4-d 结果绑定（D2 已裁决：不写入 `docs/ai_rules.md`）**：全量测试结果必须绑定解释器事实，外部解释器结果不得作为回归基线——该约束落在**本项目**的设计/CI 层（conftest 预检 + 报告指纹 + §9 A6），不升级为全局 AI 规则。理由：被约束的是"本仓库的测试入口"，不是"模型该怎么思考"；写进全局规则会让换仓库/换工具链的场景被无谓限制，且规则层无法验证自己是否被遵守。

**诊断输出（S4-a 的产出形态）**

```text
[环境预检失败] 缺 3 个必装依赖：Crypto(pycryptodome) / lark_oapi(lark-oapi) / prompt_toolkit(prompt-toolkit)
  当前解释器: /opt/homebrew/bin/python3   (3.14.6)
  期望解释器: <repo>/.venv/bin/python     (3.13.13)
  修复: <repo>/.venv/bin/python -m pytest <args>          # 推荐
        或  pip install -e ".[dev]"                        # 重建依赖
  reason_code=env_missing_dependency
  跳过预检: LFL_SKIP_ENV_PREFLIGHT=1（报告中会标注 preflight=skipped）
```

> 对照实测：系统解释器下同一个收集命令产生 107 条 collection error，其中 100 条由 `Crypto` 引起（F11）。这条诊断把"107 条各自为战的 ImportError"折叠成"1 条能直接照做的话"。
>
> `reportlab` **不在此列表**：它属 dev extra（F9），由 S4-c 的 `importorskip` 处理，不参与硬性预检。

**失败模式**

| ID | 场景 | 处置 |
|---|---|---|
| M10 | 预检硬失败拦住了"只想跑单个文件"的调试 | 缺必装依赖 → 必须退出（import 链已断，跑下去也无意义）；仅解释器非 `.venv` 且依赖齐全 → 只 warning |
| M11 | 预检自身误报/有副作用 | 用 `find_spec` 而非真实 import；提供 `LFL_SKIP_ENV_PREFLIGHT=1` 逃生阀并在报告中标注"已跳过预检" |
| M12 | 有人装了一部分依赖，报错信息不完整 | 诊断必须一次列出**全部**缺失模块 + 一条可直接粘贴的安装命令 |

> 这条改动是本设计里"投入最小、信号恢复最大"的一项：40 行代码把 107 条噪声变成 1 条可执行诊断。

### 4.5 E5 契约不漂移（P2）

**事实**：F14。9 条偏差里 4 条是命名/落点/初值（`reason_code` 命名、coordination 工具落点、`version` 初值）。它们都不影响功能，但每条都要一次往返确认——真实成本是**评审带宽**，不是正确性。

**根因**：设计文本里的契约是**散文**，无法被机器比较；实现落地时最省力的路径是"就近命名"，而散文不会反抗。

**设计**

- **S5-a 文档内嵌 `yaml contract` 块**（见 §5）：字段化描述契约点（id / kind / 名称 / 类型 / 默认 / 触发 / 可观测断言）。
- **S5-b `scripts/gen_contract_tests.py`**：解析块 → 生成 `tests/contract/test_gen_<doc>.py`，每个契约点一条运行时断言。
- **S5-c CI 一致性门**：文档块与代码 registry 不一致即 fail，输出"文档第 X 行 vs 代码第 Y 行"。
- **S5-d 腐化方向锁定**：**文档为源、代码为被检对象**。绝不从代码反生成文档——那样文档只是代码的影子，设计失去独立价值。

**边界**

- 只覆盖**跨组件契约**（tool schema、reason_code、事件名、回执字段），不覆盖内部函数签名。
- 解析失败必须显式报错：**"没解析到" ≠ "没有契约"**。

**失败模式**

| ID | 场景 | 处置 |
|---|---|---|
| M13 | 代码改了、文档没改，生成器读到旧文档 → 测试仍全绿 | 生成的测试断言**运行时行为**（真调工具看回执），文档块只提供期望值骨架；代码漂移必然踩空 |
| M14 | 契约测试过多拖慢 CI | 只对 P0/P1 契约点生成，全部为本地纯断言，无网络无 IO |

---

## 5. 契约变更表（本文档为源，机器可校验）

```yaml
contract_version: 1
doc: DESIGN-20261101-efficiency-hardening-v1
items:
  - id: C-E4-01
    kind: reason_code
    code: env_missing_dependency
    trigger: 预检发现必装依赖不可导入
    assert: 进程单条诊断退出，文本含该 code + 全部缺失模块名 + 一条安装命令
  - id: C-E4-02
    kind: reason_code
    code: env_not_venv
    trigger: 解释器非仓库 .venv 但依赖齐全
    assert: 报告头出现 warning 行，含实际解释器路径与期望路径
  - id: C-E1-01
    kind: reason_code
    code: workspace_busy
    trigger: 静默门判定近 T 分钟存在写入
    assert: 拒绝搬迁，回执含 code + earliest_retry_at
  - id: C-E1-02
    kind: event
    name: git_worktree_relocated
    fields: [created_at, actor, stash_ref, backup_dir, tracked_count, untracked_count, restore_cmds_digest]
    assert: event_stream(scope=workspace) 可检索到，字段齐全
  - id: C-E1-03
    kind: tool
    name: workspace_recovery_status
    params:
      window_hours: {type: int, default: 24}
    returns: [dirty_count, last_relocation_at, backup_dir, restore_cmds, head_matches, degraded]
    assert: 无搬迁记录时 degraded=true 且不伪报空列表
  - id: C-E2-01
    kind: receipt_field
    tool: spawn_subagent
    field: model_source
    enum: [specified, inherit_default, legacy_default]
    assert: 不传 model 时为 inherit_default 且回执含一行提示
  - id: C-E3-01
    kind: receipt_field
    tool: subagent_result
    field: terminal_reason
    enum: [completed, failed, parent_stop, truncated_rounds, lease_lost, error, orphan_reaped]
    assert: 终态回执必含该字段，取值在枚举内；`truncated_rounds` 与 `lease_lost` 不得合并成 timeout
  - id: C-E3-04
    kind: receipt_field
    tool: subagent_result
    field: cancel_origin
    enum: [parent_stop, external_cancel, reaper]
    assert: 取消来源参数化后按发起方写入；旧路径仍写常量即为未完成
  - id: C-E3-02
    kind: receipt_field
    tool: subagent_result
    field: files_written
    type: "list[path] | unavailable"
    assert: 未声明 write_scope 时为 unavailable，绝不为空列表
  - id: C-E3-03
    kind: event
    name: subagent_stalled
    fields: [child_id, last_activity_at, stalled_for_s, threshold_s]
    assert: 仅告警事件，不触发 kill
```

---

## 6. 跨方案失败模式矩阵

| 风险 | 触发条件 | 影响 | 已有缓解 | 残余 |
|---|---|---|---|---|
| 新增检查成为新的阻塞面 | 预检/静默门误判 | 本可运行的任务跑不起来 | C1 约束：只"诊断或降级"，必装依赖缺失才硬退 | 逃生阀本身可能被滥用 |
| 恢复反而放大破坏 | 恢复命令在有新写入的树上执行 | 覆盖他人改动 | `--check` 先行 + 冲突写 `restored/` | 用户手工绕开脚本 |
| 观测字段说谎 | 用空列表/0 冒充"没有" | 归因结论错误，比没数据更糟 | C4：统一 `unavailable` | 消费方可能把 `unavailable` 当空 |
| 契约门误报 | 文档与 registry 表述差异 | CI 红灯但不影响功能 | 只断言运行时行为，不比字符串格式 | 生成器解析边界 |
| 备份随 `/tmp` 消失 | 系统清理 | 搬迁后无法恢复 | S1 的 M4（复制到 `.git/lfl-prebackup/`） | 仍限本机 |

---

## 7. 拷问记录

### 7.1 方法与局限（先说实话）

本次调用的 `grill_me` 返回的是**通用维度骨架**（edge_cases / failure_modes / security / scale / ux），内容不针对本文设计生成。因此下面的问答**不是工具产出的洞见**，而是我在它给出的 5 个维度上逐条自问自答；每条只保留"**答案与直觉相反、并因此改了设计**"的部分，其余从略。

局限：**它无法拷问"我是否漏掉了第 6 个问题"**。建议实施前按 RULE-AI-28 起独立审查子代理做交叉验证，而不是相信本文的自审。

### 7.2 被推翻的前提（拷问的实际产出）

| # | 我原来的说法 | 拷问后的事实 | 改动 |
|---|---|---|---|
| P1 | "缺依赖让数百用例常年失败，应打 `optional_dep` 标记" | 三个依赖是**必装**（F9）；换解释器后 107 errors → 0（F11） | E4 整体重写为"环境自证"；`optional_dep` 方案**废弃** |
| P2 | "回执没有回显所用模型" | 回显存在（F5 `spawn_subagent.py:385`） | E2 收窄为"缺来源分支"，并承认上一轮是我读漏了 |
| P3 | "子代理无产出静默消失，父会话拿不到任何摘要" | 终态有 reports / 轨迹头 10 / final_answer（F6） | E3 重定义为"归因字段缺失 + 尾部截断" |
| P4 | "备份到 `/tmp` 就算有恢复能力" | `/tmp` 会被系统清理；且无 `restore_cmds`（F4） | 新增 M4：凭据复制到 `.git/lfl-prebackup/` |

### 7.3 五个维度的自问自答

| 维度 | 追问 | 我的回答 | 是否改设计 |
|---|---|---|---|
| edge_cases | 静默门会不会把推送无限期挂住？ | 会。所以门是"**拒绝 + 给最早可重试时刻**"，不是"等待"；超窗仍需人显式 `--allow-dirty` | 是（S1-d 加 `earliest_retry_at`） |
| edge_cases | 恢复时有新写入怎么办？ | 先 `--check`；冲突不覆盖，写 `restored/` | 是（M1） |
| edge_cases | 只跑单个测试文件也要拦吗？ | 不拦。缺**必装**依赖才硬退；仅解释器非 venv → warning | 是（M10） |
| failure_modes | 观测字段最坏的失败是什么？ | 不是"没有数据"，是"**用空列表冒充没写过**"——它会让父会话做出错误的接管决策 | 是（C4 + R10） |
| failure_modes | 契约门会不会变成新的形式主义？ | 会，如果测试断言的是"文档字段"而不是"运行时行为" | 是（M13） |
| failure_modes | 取消原因会不会全部误判成 `parent_stop`？ | 会，因为父 Stop 与手动取消都置同一标志 | 是（M7 `cancel_origin`） |
| security | `--allow-dirty` 谁能用？ | 只能是管线 owner（人）。模型侧工具白名单不含该参数 | 是（C3） |
| security | 恢复脚本会不会成为任意文件覆盖的后门？ | 会，若它接受任意目录参数 → 限定只消费 `LATEST.json` 且目录必须在 `/tmp/lfl-prebackup*` 或 `.git/lfl-prebackup/` 内 | 是（S1-a 加路径围栏） |
| scale | 107 条噪声降到 1 条，判决依据是什么？ | 预检 O(依赖数)，常数级；收益是"红灯重新有意义" | 否（本就如此） |
| scale | 契约测试会不会拖慢全量？ | 9 条纯本地断言，可忽略；风险在生成器维护成本，故限 P0/P1 | 是（M14） |
| ux | 模型发现"文件突然变干净"时，30 秒内能自诊吗？ | 原来不能（只能翻 `/tmp`）。`workspace_recovery_status` 一次调用给出结论 | 是（R4） |
| ux | 回执字段变多会不会更难读？ | 会。所以 `inherit_default` 只加**一行**提示，其余走字段不占正文 | 是（M5） |

---

## 8. 分期与工作量

| 期 | 内容 | 估时 | 前置依赖 |
|---|---|---|---|
| **P0** | E4-a/b/c（conftest 预检 + 环境指纹 + reportlab importorskip） | 0.5 人日 | 无 |
| **P0** | E1-a/b/e（`restore_prebackup.sh` + `workspace_recovery_status` 只读工具） | 1 人日 | 无（消费端可先落地） |
| **P0** | E1-c 降级登账（恢复脚本首次调用时补登 `retro=true` 事件） | 0.2 人日 | E1-a |
| **P1** | E2（`model_source` / `parent_model_at_spawn`） | 0.3 人日 | 无 |
| **P1** | E3-a/b/c/d（`terminal_reason` / head3+tail7 / `files_written` / `last_activity_at`） | 1.2 人日 | 写侧审计同源 |
| **P2** | E5（契约块解析 + 生成器 + CI 门） | 2 人日 | 本文档 §5 已具备试点数据 |
| **P2** | E3-e（`subagent_stalled` 事件） | 0.5 人日 | F8 心跳源 |
| **管线侧** | E1-d 静默门 + `LATEST.json` 生成 + `--allow-dirty` | 未知 | **不在本仓库**，需交付管线 owner 排期 |

**排序理由**：P0 两项都是"零产品风险 + 立刻恢复信号"，先做；E1 的生成端在外部，所以本仓库先做消费端，不被阻塞。

---

## 9. 验收判据（什么时候算"做完了"）

| 验收 | 对应 | 判定动作 | 通过条件 |
|---|---|---|---|
| A1 | R1 | 检查任一次搬迁后的 `LATEST.json` | `restore_cmds` ≥3 条，字段齐全，路径围栏成立 |
| A2 | R1/M4 | 搬迁后 24h 检查 `.git/lfl-prebackup/` | 存在 `LATEST.json` + patch 副本 |
| A3 | R2 | 查 workspace 事件流 | 能检索到 `git_worktree_relocated`，字段齐全（降级场景含 `retro=true`） |
| A4 | R3 | 制造未提交变更后触发搬迁 | 被拒，`reason_code=workspace_busy` 且含 `earliest_retry_at`（**需管线侧配合才能验**） |
| A5 | R5 | 用系统解释器跑全量 | 退出码非 0，输出**恰好一条**诊断，collection error 数 = 0 |
| A6 | R5/M12 | 同上 | 诊断一次列全 4 个缺失模块 + 一条安装命令 |
| A7 | R6 | 看报告头/junit 属性 | 含实际解释器路径与 Python 版本 |
| A8 | R7 | 不传 model 起子代理 | 回执含 `model_source=inherit_default` 且有一行提示；显式传参时为 `specified` |
| A9 | R8 | 父会话 Stop 掉正在跑的子代理 | `terminal_reason=parent_stop`；非父因取消时为对应枚举 |
| A10 | R9 | 子代理跑 >12 步后中止 | 轨迹含最后 7 条（尾部覆盖），且总条数仍为 10 |
| A11 | R10 | 声明 write_scope 的 child 中止 | `files_written` 非空；未声明时为 `unavailable`（**不得为空列表**） |
| A12 | R12 | 故意改一处 `reason_code` 命名 | CI 门失败并指出条目 ID（如 `C-E4-01`） |

> **不算通过的情形**（防止自欺）：A1–A3 只验"消费端能读"，不宣称"搬迁管线已合规"；A4 在管线侧改造前一律标 **未验收**。

---

## 10. 待裁决点

| ID | 问题 | 我的建议 | 谁定 |
|---|---|---|---|
| **D1** | `--allow-dirty`（越过静默门）的授权主体 | 仅管线 owner（人）可配；模型侧工具白名单**不含**该参数 | **采纳（2026-11-01）**：仅人可配；模型侧不提供该参数 |
| **D2** | 是否把"全量测试必须经 `.venv` / `ci_gate.sh`"写进 `docs/ai_rules.md` | 建议写入（R5 的制度化），但规则变更需明确批准 | **驳回写入**：约束落在本项目设计/CI 层（见 S4-d），不进全局规则 |
| **D3** | E1 是否直接升级为"独立 worktree 推送"根治 | 建议先做 P0 消费端；worktree 方案单独立项（`.venv`/相对路径兼容需实测） | **采纳立项**：P0 消费端先落地，worktree 根治单独立项跟踪（不做半成品混合改造） |
| **D4** | 上一轮 L1–L4 改动（现存在于 stash 与 `/tmp` 备份）是否恢复、何时提交 | 建议**先恢复并提交**，再动本设计——否则 stash 越积越多，恢复成本上升 | **采纳并执行**：先从 `stash@{0}`（`ce205a4da` 基线）恢复 5 个 modified + 1 个新模块 + 5 个测试 + 上轮设计文档，跑定向测试，独立审查后单独提交；`stash@{2}` 里的 scheduler 改动属另一条在飞工作，**不并入本次提交** |

---

## 11. 残余风险与非目标

**残余风险**

1. E1 的根治（静默门、`LATEST.json` 生成）**不在本仓库**，本设计只能让"被搬走"变得可发现、可恢复，不能让它不发生。
2. `.git/lfl-prebackup/` 仍是**本机单点**，不跨机器、不跨容器。
3. `files_written` 对跨进程 child 不可得 → 归因能力有限（接受，报 `unavailable`）。
4. E5 的生成器自身需要维护；若长期无人管，会退化成"没人看的测试"。
5. 本文不解决"5 项问题之外"的损耗，例如长回执本身的信噪比问题。

**非目标**

- 不追求"让全量测试变绿"——只追求"红灯有信息量"。
- 不做子代理自动重启/自动接管。
- 不给任何工具增加"自动修复工作树"的能力。

---

## 12. 与上一轮工作的关系

- 上一轮 L1–L4（归属仲裁、只读视图、跨 goal 依赖、版本 CAS）**未提交**，现存于 `git stash`（3 条）与 `/tmp/lfl-xsession-backup/`（F15）。本设计不依赖它们，也不修改它们。
- 建议顺序：**先按 D4 恢复并提交上一轮**（已有 104 项定向测试通过），再按本文 §8 推 P0——否则每次搬迁都会让"待恢复资产"多一份。
- 本文与上一轮设计的关系是**互补而非替代**：上一轮解决"多会话互踩 goal"，本文解决"管线搬走工作树"与"子代理/环境不可自证"。

---

## 13. 落实状态（2026-11-01 追加）

### 13.1 D4 已完成

- 从 `stash@{0}`（`ce205a4da` 基线）恢复 5 个 modified + `goal_coordination.py` + 5 个测试 + 上轮设计文档；`stash@{2}` 的 scheduler 在飞改动**未并入**。
- 独立只读审查（glm-5.3，只读 diff）结论：**P0 = 0，P1 = 5**；5 条 P1 全部修复并加回归测试（`tests/unit/test_l1l2_review_fixes.py`）。
- 提交 `2f538f58b`：定向 159 passed（`-k "goal or task_state or frontier or coordination or cross_session"`）。

审查发现的 5 条 P1 摘要（均已修）：

| # | 症状 | 修法 |
|---|---|---|
| P1-1 | `deadline_at` 无时区 → 与 tz-aware `now` 比较抛 `TypeError`，冒到 `task_frontier` | 入库补本地时区 + 比较侧兜底 |
| P1-2 | 单条 goal 记录不可解析 → 整个协调视图崩 | 降级条目（形状一致、`version=0`、`degraded` 标注，不伪造结论） |
| P1-3 | 协调视图默认 1h / `only_in_flight=false`，与上轮设计 §170 相反 | 改 24h / `true`，工具 schema 同步 |
| P1-4 | 判环在锁外 → 两条反向边并发可双双通过 | 判环进锁；**并补进程内 `threading` 锁**——实测 macOS 上 flock 对同进程多 fd 不自冲突 |
| P1-5 | `task_*` 拒绝文案写"加 `cross_session=true` 重试"，但该工具不收此参数 → 死循环 | 按工具能力分支，只留真实出口 |

### 13.2 D1 / D2 / D3

- **D1 采纳**：`--allow-dirty` 仅人可配，模型侧不提供该参数（写入 §10 表）。
- **D2 驳回写入 `ai_rules.md`**：约束落在本项目 conftest 预检 + 报告指纹 + §9 A6（见 S4-d 改写）。
- **D3 已立项**：`docs/design/DESIGN-20261101-worktree-push-brief.md`（P2，只论证不改行为）。

### 13.3 新增事实 F17（审查期间实测）

`PYTHONPATH` 在本机被钉在 `<repo>/.releases/<sha>/src`，因此**裸解释器 `import llm_loop` 读到的是 release 快照**；而 pytest 因 `pyproject.toml` 的 `pythonpath=["src"]`（相对 rootdir）测的是当前树。

→ 影响 E4：环境指纹只记"解释器路径 + 版本"**不足以**判定"这次测的是哪棵树"，必须追加 `source=<module origin>`。这也是 D3 brief 里的 W5。

### 13.4 本轮落地清单（2026-11-01）

| 提交 | 内容 | 验证 |
|---|---|---|
| `2f538f58b` | L1–L4 恢复 + 审查 5 条 P1 修复 | 定向 159 passed |
| `7723a5aa8` | 本设计 v1 + D3 立项说明 + E2 调查 | 文档 |
| `5ed8bf875` | P0-E4 环境预检 + 指纹 + reportlab 跳过 | 系统 3.14 → 单条诊断 EXIT=10；`.venv` → 30 passed + header |
| `0c3ba0e96` | P0-E1 消费端 + 收口门抽函数 + 棘轮登记 | 17 新测 + 定向 188 passed |

**E1 的真实数据验收**（不是夹具）：

```
bash scripts/restore_prebackup.sh --check --dir /tmp/lfl-prebackup4-20261101-113144
→ exit=4, derived=true, tracked_state=already_applied, 列出待恢复 untracked，自动跳过 AppleDouble `._*`
bash scripts/restore_prebackup.sh --check --dir /etc
→ exit=2, reason_code=path_outside_fence（围栏真实生效）
```

**本轮最有力的证据是它自己发生的**：11:31:44 推送管线第 4 次执行"清场"，把正在进行的 E1/E4 产物（含已改好的 `tests/conftest.py`）整体 stash 掉，工作树瞬时回到干净态。我从 `stash@{0}` 恢复后才继续。这就是 §1 说的问题，不是假想。

**未闭合项（如实记录）**：

- `tests/unit/test_arch_guards.py` 仍红，5 条全在本次未触碰的文件：`experiences/store.py::record_use`（148→149）、`introspection/settlement.py::_submit_one`（147→152）、`tools/review_host_admission.py` 的 `_source_snapshot`（173→222）、`poll`（124 未登记）、`start`（190→192）。属另外在飞工作线的既有漂移；**没有**为了变绿而放宽基线。
- E1 的 `--check` 对"已应用"判定依赖 `git apply --reverse --check`，在部分 hunk 已提交的仓库里可能判成 `partial`（本次真实运行是 `already_applied`，未覆盖该分支）。
- §11 P1 里"消费端拿到 LATEST.json"的前提仍不成立（管线不在本仓库，D1 裁决只约束授权主体）。
