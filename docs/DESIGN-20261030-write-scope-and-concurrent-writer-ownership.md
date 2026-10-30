# LFL 写侧路径归属与并发写者可见性：需求与实现设计（R1）

- 文档状态：**P0 已实现并通过验收**（2026-10-30）；P1/P2 未启动。实现事实见 §12。
- 日期：2026-10-30
- 适用范围：LFL 子代理 / 并行写者场景的**写侧**授权与冲突可见性
- 边界声明：本设计只约束 LFL 自身运行时写侧通道。**它不是安全沙箱**，不能用于运行不可信代码。

---

## 0. 阅读指引

| 章节 | 内容 |
|---|---|
| §1 | 问题陈述与本轮实证基线（带 file:line） |
| §2 | 范围（In / Out of scope） |
| §3 | 需求条目 FR / NFR |
| §4 | 拷问记录：25 问逐条应答 + 第 2 层 4 问 + 暴露的新盲点（设计推导的证据链） |
| §5 | 设计（数据模型、落点、判定算法、拒绝契约、冲突判定） |
| §6 | 与既有资产的复用表 |
| §7 | 测试计划 |
| §8 | 观测与指标 |
| §9 | 残余逃逸口（诚实清单） |
| §10 | 落地顺序与门禁 |
| §11 | 未决问题 |

---

## 1. 问题陈述与实证基线

### 1.1 问题

上一轮分析结论是结构同构判断：多写者共享资源时，"帮忙式越权"会把伤害落在不在场的第三方。LFL 现状把审查闸做在了**动作级别**（RULE-AI-28 三闸、`review_host_admission.py`），但**写权限只划到工具级，没有划到路径级**：

- 子代理未声明 `requires.tools` 时继承父全量工具面，含 `edit_file` / `execute_command`；
- 仓库无 `CODEOWNERS`，全仓库无 `writable_paths` / `path_scope` / `allowed_paths` / `write_scope` 任何形态的路径归属概念（对 `src` 全量内容搜索无命中）；
- `requires.fs_isolation` 非默认开启，且它明确**不是**安全沙箱。

结果是：一个只被委派"改一个文件"的子代理，**在机制上**可以改整个仓库。

### 1.2 本轮实证基线（全部经本轮工具读取，非记忆）

| 编号 | 事实 | 出处 |
|---|---|---|
| F1 | `_compute_child_tool_scope`：声明 `requires.tools` 即程序级强制白名单；**声明超出父 scope 直接拒绝**（授权只降不升，fail-fast 而非静默截断）；未声明则继承父 scope | `src/llm_loop/subagent/runner.py:1390-1426` |
| F2 | `start()` 在**预留任何 child 资源之前**计算 scope 并拒绝（fail-fast 语义） | `src/llm_loop/subagent/runner.py:1453-1463` |
| F3 | 父 scope 通过 ContextVar 传递：`parent_scope = current_tool_discovery_scope.get()`；child 内 `current_tool_discovery_scope.set(child_scope)` + `current_workspace_root.set(worktree_lease.path)` | `runner.py:1404`、`runner.py:1656`、`runner.py:1664`；ContextVar 定义 `src/llm_loop/core/run_context.py:40-41`（workspace_root）、`:65-66`（tool_discovery_scope） |
| F4 | 既有能力矩阵：`SurfaceCapability` / `SurfaceRequirements(from_kwargs, declared)` / `local_subagent_capability` / `codearts_capability` / `validate_requirements` / `alternatives_hint`（5 个能力位） | `src/llm_loop/core/execution_surface.py:44, 78, 91, 116, 126, 162, 178, 229` |
| F5 | `requires` 是既有声明位：`tools` / `network` / `fs` / `fs_isolation` / `session_continuity`；非法结构 → `from_kwargs` 返回 None → 回参数错误 | `src/llm_loop/tools/builtin/spawn_subagent.py:183-194` |
| F6 | `requires.tools=[]`（或全空白项）历史被静默当作继承，**已改为确定性参数错误**（唯一豁免：程序 pin 的 canary 直发零工具诊断 child） | `spawn_subagent.py:195-218` |
| F7 | 隔离 worktree：非默认开启；**失败即拒绝，绝不降级共享工作区**；脏树保守保留、不自动合并；`ORPHAN_TTL_S=24*3600`、`MIN_FREE_BYTES=512MB`、`MAX_KEPT_DIRTY=8` | `src/llm_loop/workspace/worktree_isolation.py:1-17`（约定 docstring）、`:32-38`（常量）、`:241-253`（磁盘/上限 fail-fast） |
| F8 | 既有"路径 + 命令"双口径封条先例：`sealed_path_reason` / `sealed_command_reason`；归一 `_norm` = expanduser → 相对路径拼工作区根 → `realpath`（不要求文件存在）；darwin `casefold`；**内部异常 fail-open 放行 + warning**；已知残余自陈（变量拼接/编码绕过、不做 shell 语义解析） | `src/llm_loop/sealed_paths.py:107-108`（`_norm`）、`:158`、`:185`、`:203-204`（fail-open） |
| F9 | `edit_file` 侧已有：`_ToolJournalFileEffectSink`（`prepared/observed/mutation_authority/records_durable`）、`workspace_scope=workspace_root`、`_symlink_write_guard`（fail-closed）、`_map_service_error` / `_fail(msg, error_type)` | `src/llm_loop/tools/builtin/edit_file.py:27`（sink）、`:34`（workspace_scope）、`:175`（symlink guard）、`:196`（run）、`:265`（_map_service_error）、`:472`（_fail） |
| F10 | **`FileService` 是写侧统一栅栏**：`edit(..., effect_sink, workspace_scope, expected_snapshot_ref, whole_file)`、`observe(...)`、`_canonical_scope` / `_relative_to_scope` / `_path_lock`；类注释自述为 "Exact-byte single-file core shared by coordinated writers" | `src/llm_loop/workspace/file_service.py:135`（_canonical_scope）、`:139`（_relative_to_scope）、`:157`（_path_lock）、`:195`（observe）、`:283`（edit）、`:293`（expected_snapshot_ref 参数）、`:341-348`（版本前置校验） |
| F11 | 既有 shell 段级解析能力可复用：`_shell_segments` / `_strip_payload_units` / `classify_host_shell`；敏感路径拒审 `review_sensitive_tracked_path_refused`；git 状态不可用即 `git_state_unavailable` | `src/llm_loop/tools/review_host_admission.py:271`、`:414`、`:604`、`:675`、`:839` |
| F12 | 既有只读命令分类器：`is_read_only_probe` / `classify_review_gate_command` / `make_review_gate_probe` | `src/llm_loop/tools/review_gate.py:61`、`:133`、`:159` |
| F13 | 仓库根 = 当前工作区根（本机绝对路径按仓库卫生不入库）；本轮 `git status --porcelain` 有 26 条未提交条目 | 本轮 `execute_command` |
| **F14** | **子代理有两条启动路径，各自独立计算并注入 scope**：异步 `start()` 路径（`:1428` 定义、`:1455` 计算、`:1656`/`:1664` 注入）与同步 `run()` 路径（`:2354` 计算、`:2368`/`:2431` 注入）。代码注释明写 `start()` 面的 spawn_subagent 剔除是"异步舰队防递归设计，**不自动带入同步路径**" | `src/llm_loop/subagent/runner.py:2339-2346`（注释）、`:2354`、`:2368`、`:2431` |

> 关于背景论文：对话中给出的论文编号**未在本轮独立核验**（未重新抓取 arXiv 条目）。本文不依赖该编号的任何具体结论，只依赖对话中已陈述的机制描述（资源级权限闸缺失 → 帮忙路径产生越权伤害）。

---

## 2. 范围

### 2.1 In scope

1. 子代理写侧**路径级**授权的声明、继承、求交、强制点、拒绝契约。
2. 同一工作树上**并发写者**的可观测性：谁在写哪个路径、写是否基于过期基线。
3. 只读观测面：让父会话能看见"实际写集合"与"冲突"。
4. 受保护路径的默认只读策略与外部锚预留。

### 2.2 Out of scope（明确不做）

1. **不**做安全沙箱。`execute_command` 可运行任意代码；本设计只做写侧归属与取证，不提供不可信代码隔离。
2. **不**替换 `fs_isolation`。两者是同一问题的两层：隔离优先（见 §5.9）。
3. **不**做跨机 / 跨仓库副本的写侧管控（WAL 视野外）。
4. **不**改 `task_create` 的 `acceptance` 语义（自由文本验收清单；§5.8 的锚点另设结构化字段，不混入 acceptance）。
5. **不**对父会话自身施加路径限制（父是授权来源，不是被授权对象）。

---

## 3. 需求

### 3.1 功能需求

| ID | 需求 | 验收口径 |
|---|---|---|
| FR-1 | 子代理可声明写侧路径集合 `requires.write_scope.paths` | 声明非法 → spawn 阶段参数错误（与 `requires.tools=[]` 同级确定性拒绝） |
| FR-2 | 有效 scope = 三层求交：child 请求 ∩ 父 scope ∩ （P2）外部锚 | child 请求超出父 → **refused**，detail 列出越界项；**不静默截断** |
| FR-3 | 未声明 `write_scope` → 继承父 scope（父为全量时子为全量），零行为变化 | 既有测试全绿；既有 spawn 调用不回执新增字段 |
| FR-4 | 显式空 `paths: []` = 只读子代理 | 任何写操作被确定性拒绝，回执 `error_type=write_scope_violation` |
| FR-5 | 越界写被拒绝且**不产生副作用** | 拒绝后目标文件字节不变；不产生半成品 |
| FR-6 | glob 语义确定、边界安全 | `src/**` 命中 `src/a/b.py`；`src*` 不得命中 `srcevil/x.py`（路径分隔符边界判定） |
| FR-7 | symlink 逃逸被拒 | scope 内 symlink 指向 scope 外 → 拒绝（`realpath` 后判定） |
| FR-8 | `execute_command` 的绝对路径越界被拒；无法静态判定时**显式标记为未验证**并留审计 | 回执/审计事件含 `scope_unverified`，不得静默当作"已验证通过" |
| FR-9 | 并发写冲突可检出：写入基线与磁盘当前不一致且该基线由**其他写者**产生 | 事件落 `event_log`，含 path / writer / 基线 sha |
| FR-10 | 合法顺序写不误报 | 写者 A 写完 → 写者 B 基于 A 的结果写 → 不产生冲突事件 |
| FR-11 | 观测面：父会话可查"本 child 实际写了哪些路径 / 越界尝试次数 / 当前活跃写者" | 只读工具 + `task_frontier` 视图 |
| FR-12 | 受保护路径默认对子代理只读 | 保护清单可配置；解锁需显式声明 + 审计事件 |

### 3.2 非功能需求

| ID | 需求 | 口径 |
|---|---|---|
| NFR-1 | 判定开销可忽略 | 单次判定 O(patterns × path parts)，预编译 + 缓存；热路径不做 git 调用 |
| NFR-2 | 不引入新概念 | 声明仍写在既有 `requires` 块内，与 `requires.tools` 同级 |
| NFR-3 | 拒绝信息可自助修复 | 回执给出：实际路径、允许的 pattern 集合、修正方式；不含堆栈、不回显文件内容 |
| NFR-4 | 跨版本 fail-closed | 父用新字段派子、子端不识别 → 拒绝该声明（不静默忽略） |
| NFR-5 | 先保真再优化 | RULE-AI-24：P0 只做"阻止 + 取证"，不做性能改造，不改既有写路径语义 |
| NFR-6 | 审查前置 | 本设计若进入实现，代码全量测试前须过 RULE-AI-28 独立审查闸 |

---

## 4. 拷问记录（设计推导证据链）

> 说明：`grill_me` 工具每次调用均返回**同一层**清单、不支持递进（连续三次实测，焦点域轮换覆盖全部 5 领域 25 问）。第 2 层 4 问为自拟递进追问，直接针对本设计最脆弱处。

### 4.1 第 1 层：25 问逐条应答

#### edge_cases

| 问 | 应答 |
|---|---|
| 输入为空/null/0/超长 | 三态区分：**未声明** = 继承父；**显式 `[]`** = 只读；**非法结构** = 参数错误。条目上限 64、单条 ≤512 字符，与既有 `from_kwargs` 风格一致，超限返回 None → 调用方回参数错误 |
| 时钟/网络/磁盘满 | scope 判定是**纯路径计算**（不读时钟、不联网）；scope 在 spawn 时冻结 → 时钟偏移不影响判定。磁盘满由既有原子写保证不留半成品，回 `WriteFailed` |
| 同一操作并发 100 次 | 判定无状态、幂等；同文件并发写属 §5.7 冲突检测域，不在 scope 语义内 |
| 身份/权限缺失 | 不引入新身份概念。父 scope 为"全量"时子继承全量；子声明超出父 → fail-fast 拒绝（沿用 F1 语义） |
| 配置/依赖版本不一致 | 父检测子端 capability 标识，不识别 `write_scope` 字段 → 拒绝该 spawn（fail-closed）；旧调用不传字段 → 零回归 |

#### failure_modes

| 问 | 应答 |
|---|---|
| 最坏失败场景 | scope 被绕过：①模型自声明 scope 不构成授权；②`execute_command` 任意写；③ cp 通道不经 `FileService`。**数据不丢**，归属失效；已写入内容可经 WAL 检出 |
| 可恢复性 | 越界拒绝 = 改声明重派（可恢复）；已写入越界内容需人工回退（WAL 给出基线可定位） |
| 检测 | 回执 `error_type=write_scope_violation` + `event_log` + 指标（§8） |
| 重试策略 | 越界是确定性失败 → **不自动重试**（重试无意义且掩盖问题） |
| 错误信息友好 | 给"实际路径 / 允许 pattern / 修正方式"，不含堆栈、不回显文件内容（对齐 F8 的口径纪律） |

#### scale

| 问 | 应答 |
|---|---|
| 1000× 增长瓶颈 | ①pattern 匹配次数；②目录级 sweep（冲突兜底）。前者预编译 + 缓存；后者只在校验点惰性跑，不在热路径 |
| 热/冷路径 | 热 = 写前判定（内存内）；冷 = 事件落盘、指标聚合、目录 sweep |
| 缓存策略 | scope 在 spawn 时冻结不可变 → 判定缓存**无需失效**；仅父 scope 变更时重算。父 scope 变更 = 父会话重派，天然产生新 child |
| 状态持久化 | 复用既有 `ToolExecutionJournal` WAL（已记录 canonical_path + before/after bytes），**不新建台账**；崩溃后仍可检出 |

#### security

| 问 | 应答 |
|---|---|
| 输入可信度 | `write_scope.paths` 来自模型声明 = **不可信输入**：须 expanduser → 相对拼 `workspace_root` → `realpath` → 路径分隔符边界判定；拒绝 `..` 穿越、symlink 逃逸、绝对路径越界、通配符歧义 |
| 敏感数据 | 只记路径、pattern、sha；**不回显文件内容**（沿用 F8 纪律） |
| 权限边界 | **声明 ≠ 授权**。P0 只提供"护栏 + 取证"；真强制需外部锚（P2：CODEOWNERS / 结构化 task 锚），见 §5.8 |
| 滥用入口 | 反复 spawn 宽 scope → 全局上限（每 child pattern 数上限、scope 宽度上限、父级显式确认）+ 审计事件 `scope_widened` |

#### ux

| 问 | 应答 |
|---|---|
| 30 秒理解价值 | 报错第一句直说："该路径不在本子代理被允许写入的范围内" |
| 自助修复 | 回执给出可用 pattern 集合 + 正确声明写法（对齐 F6 `requires.tools=[]` 的报错风格） |
| 可观察入口 | 只读工具 `verify_path_scope` + `task_frontier` 扩展 writer/scope 视图 |
| 心智模型 | 不新增顶层概念：`requires` 块内加一个字段，与 `tools` 同级 |

### 4.2 第 2 层（自拟递进 4 问）

**Q1：声明 ≠ 授权，怎么落地为真强制？**
承认模型自声明只能做护栏 + 取证。真强制分两级：
- **L1（程序级）**：child scope = `child 请求 ∩ 父 scope ∩ 任务锚`。父**无权**把 scope 放宽到任务锚之外——放宽必须改任务锚（经 `task_update` 留痕），不是改一行 spawn 参数。
- **L2（外部锚）**：CODEOWNERS / 人类批准是唯一可信源；未锚定路径默认只读。
P0 交付 L1 的"父子求交"，L2 列入 P2。

**Q2：`execute_command` 逃逸口如何在不做完整 shell 解析的前提下设卡？**
沿用 F8 的既有先例口径（字面判定 + 显式残余边界），分三档：
- 档 1（P0）：命令串中的**绝对路径字面量**（经 shell 词法切分）须落在 scope 内 → 否则拒绝。相对路径 → 放行但打 `scope_unverified` 审计标记。
- 档 2（P1）：复用 F11 的 shell 段级解析（`_shell_segments` / `_strip_payload_units` / `classify_host_shell`）识别写盘命令族（`cp` / `mv` / `sed -i` / 解释器写盘等），命中且无法静态定位目标 → 拒绝或改判。
- 档 3（P2）：子进程 cwd 绑定 + 目录级约束。
**关键取舍**：P0/P1 的"命令级拦截"始终存在语义盲区；因此**更强的一条是能力面剔除**——child 的 write_scope 受限时直接从其工具面剔除 `execute_command`（连工具都不给），比运行时拦截无歧义。此项列入 P1 并与档 2 二选一，由实现期按成本决定。

**Q3：cp 通道设卡点选在哪层才不会漏？**
不在 `edit_file` 层设卡（cp 绕过它）。真正统一点是 `FileService`（F10：所有 `edit_file` 写入的唯一落盘路径）。但 cp/裸 shell **不经** `FileService`，所以任何 `FileService` 内的检查都无法覆盖它。
→ 结论分两层写清楚：
- **L1 强制点** = `FileService.edit` / `observe`（覆盖 `edit_file` 全路径，含 WAL 与 `expected_snapshot_ref` 校验）。
- **L2 兜底** = 对不经 `FileService` 的写通道，用"目录快照比对"惰性 sweep 事后检出（P1）。
诚实边界：**P0/P1 无法在运行期完全阻断 cp 通道写入**，只能在事后检出并归因（归因靠目录快照 + git blame，不精确）。要真正阻断需 P2 的子进程约束。

**Q4：并发冲突检测复用 WAL，如何避免把合法顺序写误报为冲突？**
判据不能是"写者不同"，必须是**基线失配**：写入前读到的基线 sha（`before_bytes` 的 sha256）与写入时磁盘实际 sha 不一致，且该基线 sha 由**另一个 writer_id** 在 WAL 中产生过 → 冲突。
- 合法顺序写：A 写完（after_sha=X）→ B 读到的基线正是 X → B 的 before_sha == X == 磁盘当前 sha → **不冲突**。
- 真正冲突：B 的 before_sha = Y（更早的版本），而磁盘已被 A 改成 X ≠ Y → 冲突。
`FileService` 内部有 path 级锁（F10 `_path_lock`），所以同机同进程内并发已串行化；本检测的真实价值是**跨进程 / 跨会话 / 不经 FileService 的写通道**。

### 4.3 拷问暴露的新盲点（已并入设计）

1. **`write_scope` 与 `fs_isolation` 冗余**：两者是同一问题的两层。须明确"**隔离优先**"——能隔离就用隔离，scope 只在无法隔离（共享工作树）时兜底；否则会出现"既隔离又 scope"的双重配置与心智负担。
2. **声明字段增多抬高模型填写成本**：`requires` 已 5 个字段。建议 `write_scope` **仅在** `fs_isolation=false` 且该 child 确需写文件时必填；否则省略即继承。
3. **"只降不升"与"任务锚"缺位**：现有 E4 只有父子两层（§5.3 会补第三层）。
4. **两条子代理启动路径（F14，本轮新发现）**：异步 `start()` 与同步 `run()` 各自独立计算并注入 scope；既有代码注释明确 `start()` 面的 spawn_subagent 剔除"不自动带入同步路径"。这意味着**任何只在单条路径生效的授权机制都有绕过口**——`write_scope` 必须两条路径都注入（C5/C5b），且需专门测试用例覆盖同步入口（见 T15）。

---

## 5. 设计

### 5.1 概念模型

写侧授权是**三层求交链**，任一环节收紧即收紧：

```
effective_scope(child)
  = requested(child) ∩ inherited(parent) ∩ anchor(task / CODEOWNERS)   # P2 提供 anchor
  ∖ protected_paths(默认只读清单)
```

- `requested`：child 在 `requires.write_scope.paths` 中显式声明（glob，相对 `current_workspace_root`）。
- `inherited`：父会话当前 write scope（ContextVar）；父为"全量"时该层不收紧。
- `anchor`：任务级锚（P0/P1 缺席 → 该层不收紧；P2 提供）。**父不可自行放宽此层**。

### 5.2 数据结构与解析

新增声明位（与既有 `requires` 同级）：

```json
"requires": {
  "tools": ["edit_file", "read_file"],
  "write_scope": {
    "paths": ["src/llm_loop/core/**", "docs/DESIGN-*.md"],
    "mode": "allow"
  }
}
```

- `mode`：`allow`（默认，按 paths 放行）/ `deny`（在父 scope 内按 paths 排除）。`deny` 优先于 `allow`。
- 解析位置：`SurfaceRequirements.from_kwargs`（F4）扩展 `write_scope` 键；非法结构 → 返回 None → `spawn_subagent` 回参数错误（与 F5/F6 同链路）。
- `paths: []` 语义 = 只读（FR-4）；**键不存在** = 继承（FR-3）。二者必须在解析层区分，不得合并。
- 上限：pattern 数 ≤ 64，单条 ≤ 512 字符；超限 → 参数错误。

### 5.3 落点（逐文件）

| # | 文件 | 改动 | 对应事实 |
|---|---|---|---|
| C1 | `src/llm_loop/core/execution_surface.py` | `SurfaceRequirements` 增加 `write_scope` 字段与解析；`SurfaceCapability` 增加 write scope 维度；`validate_requirements` 增加该维度比对 | F4 |
| C2 | `src/llm_loop/tools/builtin/spawn_subagent.py` | `requires` schema 增加 `write_scope`；解析失败 → 参数错误；把 scope 透传给 runner | F5、F6 |
| C3 | `src/llm_loop/subagent/runner.py` | 新增 `_compute_child_write_scope(requested)`：与父 scope 求交，越界 → 拒绝；在 `start()` **预留 child 资源之前**计算并拒绝（沿用 F2 的 fail-fast 位置） | F1、F2 |
| C4 | `src/llm_loop/core/run_context.py` | 新增 `current_write_scope: ContextVar[WriteScope | None]`（默认 None = 全量），与 `current_tool_discovery_scope` 并列 | F3 |
| **C5** | `src/llm_loop/subagent/runner.py` | **两处**注入 `current_write_scope.set(child_scope)`：异步 `start()` 路径（`:1656` 邻近）与同步 `run()` 路径（`:2368` 邻近），且两处都要在 `finally` 里恢复 token（既有 `scope_token`/`ws_token` 恢复模式，`:2347-2348`）。**只改一条路径 = 同步入口（workflow local executor）完全绕过 scope** | F3、F14 |
| C5b | `src/llm_loop/subagent/runner.py` | 同步 `run()` 路径也需在计算失败时走 refused 终态（参照 `:2354-2367` 的既有 refused 形态），确保"声明越界 → 拒绝且未启动任何 child"在两条路径一致 | F14 |
| C6 | `src/llm_loop/workspace/file_service.py` | `edit()` / `observe()` 接受 `write_scope`；在 `_canonical_scope` / `_relative_to_scope` 之后追加 scope 判定；越界抛 `FileServiceError(error_type="write_scope_violation")` | F10 |
| C7 | `src/llm_loop/tools/builtin/edit_file.py` | 把当前 `current_write_scope` 传入 `FileService`；`_map_service_error` / `_fail` 把新 error_type 映射为确定性拒绝回执 | F9 |
| C8 | `src/llm_loop/tools/builtin/execute_command.py` | P0：命令串绝对路径字面量 scope 校验 + `scope_unverified` 审计；P1：写盘命令族判定 / 能力面剔除 | F8、F11 |
| C9 | `src/llm_loop/tools/builtin/`（新只读工具） | 新增只读工具 `verify_path_scope`：报告当前 child 的有效 scope、已写路径集合、越界尝试数 | FR-11 |
| C10 | `task_frontier` 实现 | 增加 writer 视图：按 path 列出当前活跃写者 | FR-11 |

### 5.4 判定算法（write scope）

```
def scope_allows(scope, abs_path) -> (bool, reason):
    # 1. 归一（照 F8 的 _norm 口径）
    target = realpath(expanduser(abs_path))            # 不要求文件存在
    # 2. 边界判定：scope root 之下（按路径分隔符），防 tasks_evil 误命中
    if not under_any_root(target, scope.roots): return False, "outside_scope"
    # 3. deny 优先
    if matches_any(target, scope.deny): return False, "denied_by_deny_list"
    # 4. allow 集合（glob，相对 workspace_root）
    if not matches_any(target, scope.allow): return False, "not_in_allow_list"
    return True, ""
```

要点：
- 归一用 `realpath`（展开 symlink 与 `..`），**不用** `Path.resolve()`（不存在文件会抛错，F8 口径）。
- darwin 大小写不敏感 → 比较前 `casefold()`（F8 口径）。
- scope root 集合 = allow/deny glob 各自**匹配到的具体路径前缀**与声明根的并集；glob 本身不含**前缀边界**语义时（如 `src/*`），判定退化为"模式匹配 + 分隔符边界"。
- 受保护清单（`protected_paths`）在链尾统一减去，优先级高于 allow。

### 5.5 拒绝契约

- 错误类型：`error_type = "write_scope_violation"`（与 `FileServiceError` 既有 error_type 风格一致，F10）。
- 回执字段：`{实际路径, 允许 pattern 集合（截断至 N 条）, 拒绝类别(outside_scope | not_in_allow_list | denied_by_deny_list | protected_path), 修正建议}`。
- **不回显文件内容**；pattern 列表过长时截断并注明总数（F8 纪律）。
- 无副作用保证：判定发生在 `FileService` 落盘前（F10 的 edit 在锁内、原子写），拒绝后文件字节不变（NFR-5 / FR-5）。

### 5.6 `execute_command` 的处置（P0 / P1）

| 期 | 做法 | 强度 | 残余 |
|---|---|---|---|
| P0 | 命令串中的**绝对路径字面量**（经 shell 词法切分）须落在 scope 内；相对路径 → 放行 + `scope_unverified` 审计事件 | 弱（确定性字面） | 变量拼接、编码、相对路径写到 scope 外 |
| P1-a | 复用 F11 段级解析识别写盘命令族，无法静态定位目标 → 拒绝 | 中 | 解释器任意代码 |
| P1-b | 受限 scope 的 child **直接剔除 `execute_command` 工具面** | 强（无歧义） | 失去一切命令能力（含只读），需评估 |

取舍：P1-b 与 P1-a 二选一或叠加，由实现期按 child 任务实际需要决定（若 child 需跑测试，通常仍需命令能力 → 选 P1-a + 只读探针白名单 F12）。

### 5.7 并发写者可见性与冲突判定

- **记录**：复用 WAL。扩展 `FileEffectSink` 记录项，增加 `writer_id`（child_id / session_id）与 `run_id`；已有 `prepared(canonical_path, before_bytes, expected_after_bytes)` 与 `observed(...)` 足够承载基线与结果（F9、F10）。
- **判定**（写前）：
  ```
  conflict = (before_sha != current_disk_sha) and (current_disk_sha 由其他 writer_id 写入过)
  ```
  - 合法顺序写：A after_sha=X → B before_sha=X == 磁盘 → 不冲突（FR-10）。
  - 真冲突：B before_sha=Y，磁盘已被 A 写成 X≠Y → 冲突（FR-9）。
- **事件**：`event_log` 记 `concurrent_write_conflict`：`{canonical_path, expected_sha, actual_sha, writer_id, other_writer_id}`。**不阻断写入**（阻断会破坏现场），只告警 + 归因。
- **cp 通道兜底**（P1）：不经 WAL，无法归因到 writer → 用惰性目录快照比对（`git status --porcelain` + 关键文件 sha 基线，参照既有并行写者经验卡的"开工留基线"纪律），事件标 `unattributed_write`。
- **观测**：当前活跃写者按 path 分组，供 `task_frontier` 与 `verify_path_scope` 读取。

### 5.8 外部锚（P2）与受保护路径

- **受保护路径**（默认对所有 child 只读，可配置）：`docs/ai_rules.md`、`src/llm_loop/tools/**`、`.github/**`、CI 配置目录。
  解锁方式：父显式声明 + 审计事件 `scope_widened`（谁、何时、解锁了哪些路径）。
- **外部锚**：读取 `CODEOWNERS`（仓库现无此文件，需新增）+ 结构化任务锚 `task_create.scope_paths`（**不改 `acceptance` 语义**，见 §2.2）。
- **父不可自行放宽锚层**：放宽只能通过 `task_update` 改锚（留痕），这是"声明 ≠ 授权"落地的关键。

### 5.9 与 `fs_isolation` 的关系

- **隔离优先**：能开 `fs_isolation` 就开（独立 worktree，天然无并发写者，F7）。此时 `write_scope` 通常无需声明。
- **scope 兜底**：隔离不可用（父工作区非 git 仓库、磁盘不足）或需要多 child 共享同一棵树时，`write_scope` 才承担归属。
- `fs_isolation` **不是**安全沙箱（其 docstring 自陈），本设计同样不宣称是。

### 5.10 兼容与迁移

- `write_scope` 缺省 = 继承 → **既有调用零行为变化**。
- 新字段仅在 `requires` 内新增键，JSON schema 向后兼容。
- 跨版本：父检测子端 capability 标识；子端不识别 → **拒绝该 spawn**（fail-closed，NFR-4），不静默忽略。
- 不改动既有写路径语义、错误类型与回执结构（除新增一种 error_type）。

---

## 6. 与既有资产的复用表

| 既有资产 | 复用方式 | 避免的重复造轮 |
|---|---|---|
| `SurfaceRequirements` / `validate_requirements` / `alternatives_hint`（F4） | 新增 write scope 维度，复用"声明 vs 能力 → 缺口列表"的表达 | 不另造一套声明解析 |
| `_compute_child_tool_scope` + `start()` fail-fast 位置（F1、F2） | 直接沿用"只降不升 + 预留资源前拒绝"的语义与位置 | 不引入第二处 spawn 拒绝点 |
| `current_tool_discovery_scope` / `current_workspace_root` ContextVar（F3） | 新增 `current_write_scope` 与之并列，注入点相同 | 不新建子代理专用传参通道 |
| `sealed_paths` 归一口径与边界纪律（F8） | 复用 expanduser→拼根→realpath→casefold→分隔符边界 | 不重写路径归一 |
| `FileService.edit` / `observe` / `_canonical_scope` / `_relative_to_scope`（F10） | 作为唯一写侧强制点 | 不在 `edit_file` 重复实现围栏 |
| `ToolExecutionJournal` WAL（F9、F10） | 冲突检测的基线来源 | 不新建写入台账 |
| `review_host_admission` shell 段级解析（F11） | P1 识别写盘命令族 | 不自研 shell 解析 |
| `review_gate.is_read_only_probe`（F12） | 区分只读/写盘命令 | 不重复分类逻辑 |
| `review_host_admission` 敏感路径拒审（F11） | 受保护路径的既有拒审模式可参照 | 不新造拒审语义 |

---

## 7. 测试计划

按 TDD 红→绿。全部为**新增**测试，既有测试零修改即须全绿（NFR-3 零回归）。

| ID | 用例 | 期望 |
|---|---|---|
| T1 | `requires.write_scope` 非法结构（字符串 / 非数组 / 超 64 条 / 单条 >512 字符） | 参数错误，非静默忽略 |
| T2 | child 请求超出父 scope | spawn refused，detail 含越界项；**不静默截断** |
| T3 | `write_scope` 未声明 | 继承父；既有 spawn 行为与回执不变 |
| T4 | `paths: []` | 写操作被拒 `write_scope_violation`；文件字节不变 |
| T5 | glob 边界 | `src/**` 命中 `src/a/b.py`；`src*` 不命中 `srcevil/x.py` |
| T6 | scope 内 symlink 指向 scope 外 | 拒绝 |
| T7 | `..` 穿越 / 绝对路径越界 | 拒绝 |
| T8 | 拒绝路径 | 目标文件字节不变，无半成品（原子写保证） |
| T9 | `execute_command` 绝对路径越界 | 拒绝；相对路径 → 放行 + `scope_unverified` 审计事件 |
| T10 | 冲突检测 | before_sha 失配 → `concurrent_write_conflict` 事件；**不阻断写入** |
| T11 | 合法顺序写（A→B） | 无冲突事件（不误报） |
| T12 | 跨版本握手 | 子端不识别字段 → 拒绝 spawn |
| T13 | 受保护路径 | 默认拒绝；显式解锁 → 成功 + `scope_widened` 审计 |
| T14 | 观测面 | `verify_path_scope` 报告 scope / 已写集合 / 越界计数；`task_frontier` writer 视图正确 |
| T15 | **同步 `run()` 路径**（workflow local executor 同款入口）注入 write_scope | 该路径的 child 同样受 scope 约束；越界请求 → refused 且未启动任何 child |
| T16 | 两条路径的 scope 拒绝后 ContextVar 无泄漏 | 父会话后续写入不被 child 的 scope 影响（既有 token 恢复模式，F14） |
| T17 | **异步 `start()`**：child 声明受限 write scope | child 工具面剔除 `execute_command`（模型可见 schema / 工具目录 / `call_tool` 派发 / 越权直调拦截共用同一 scope 变量）；child 仍正常启动（剔除≠拒绝启动） |
| T18 | **同步 `run()`**：child 声明受限 write scope | 同 T17（两条路径同款判定，不做单路径补丁） |
| T19 | 父子均未声明 write scope | 工具面零变化：child 仍拿到 `execute_command`；回执无 `write_scope_tool_restriction` 字段 |
| T20 | 父声明受限 scope、子未声明（继承） | 子继承受限 → 同样剔除 `execute_command` |
| T21 | `requires.tools` 显式含 `execute_command` 且 child 声明受限 scope | **剔除而非拒绝启动**：child 照常启动，工具面去掉 `execute_command`，其余声明工具保留 |
| T22 | child 显式声明只读（`paths:[]`） | 视为受限 → 剔除 `execute_command` |
| T23 | child 工具面原本为全量（None） | 物化为 registry 名单去掉 `execute_command`；其余工具一个不动 |

---

## 8. 观测与指标

| 指标 | 含义 | 用途 |
|---|---|---|
| `write_scope_violation_total` | 越界拒绝次数（按 error_type / 拒绝类别分） | 判定 scope 是否过紧或存在越权尝试 |
| `scope_unverified_total` | 无法静态判定而放行的命令数 | 度量残余逃逸口规模 |
| `concurrent_write_conflict_total` | 检出冲突次数 | 并发写者是否真在发生 |
| `unattributed_write_total` | 不经 WAL 的写入检出数（cp 通道等） | 兜底检测有效性 |
| `scope_coverage_ratio` | 声明了 write_scope 的 child / 有写权限的 child | 覆盖度推进 |

事件（`event_log`）：`write_scope_violation` / `scope_widened` / `concurrent_write_conflict` / `unattributed_write` / `scope_unverified`。

---

## 9. 残余逃逸口（诚实清单，不宣称已覆盖）

1. **模型自声明 ≠ 授权**：P0/P1 是护栏 + 取证，不是强制授权。父可为自己声明宽 scope；真强制需 P2 的外部锚 + 人类批准。
2. **`execute_command` 语义盲区**：变量拼接、编码、解释器任意代码可绕过字面判定。P1-b（能力面剔除）才是无歧义手段，代价是丧失命令能力。
3. **cp / 裸 shell 通道**：不经 `FileService`，P0/P1 无法在运行期完全阻断，只能事后检出且归因不精确。
4. **跨机 / 跨仓库副本**：不在 WAL 与本机 scope 视野内。
5. **父会话自身**：不受 write_scope 约束。
6. **并发归因精度**：跨进程写的"其他写者"需依赖 WAL 记录；无 WAL 记录的写只能标 `unattributed`。
7. **误报/漏报**：冲突检测基于 sha 比对，文件内容相同但语义不同的并发写无法区分（判为不冲突）。
8. **新入口漏注入**：子代理有异步 `start()` 与同步 `run()` 两条独立路径（F14），既有代码注释已自陈"不自动带入同步路径"。P0 通过 C5/C5b 双注入 + T15/T16 覆盖，但**未来新增的第三条入口仍可能漏**——建议在实现时把 scope 注入收敛到单一封装函数（而非分散在两条路径），降低新增入口的漏注入概率。

---

## 10. 落地顺序与门禁

| 期 | 内容 | 出口门禁 |
|---|---|---|
| **P0** | C1–C7、C5b、C9 + T1–T8、T12、T15、T16 + `verify_path_scope` | RULE-AI-28 代码全量测试前独立审查 PASS；既有测试全绿 |
| **P1** | C8（命令族判定 / 能力面剔除）、C10 + T9–T11、T13、T14 + 指标与事件 | 同上 + 事件在真实并发场景被触发过至少一次 |
| **P2** | 外部锚（CODEOWNERS + `task_create.scope_paths`）+ 子进程 cwd 约束 | 需单独立项（改任务图 schema） |

每期独立可交付、可回退（feature flag 控制，默认关闭 → 逐步打开）。遵循 RULE-AI-24：先保真（阻止 + 取证），再优化。

---

## 11. 未决问题

1. `write_scope` 与 `requires.tools` 的耦合：受限 scope 的 child 是否应**自动**从工具面剔除 `execute_command`（P1-b）？自动剔除会让"只读探针"类 child 失去跑测试的能力，需产品口径决定。
2. `protected_paths` 的清单来源：写死在代码 / 配置文件 / 从 CODEOWNERS 派生？P0 取配置，P2 倾向派生。
3. 冲突事件的严重度：是否需要达到阈值即**暂停**该 child（避免"带病继续写"）？当前设计只告警。
4. `task_create.scope_paths`（P2）与 `acceptance` 的关系：完全独立字段，还是 acceptance 中约定路径语法？倾向独立字段，避免解析自由文本。
5. 度量口径：`scope_coverage_ratio` 的分母是"有写权限的 child"，需要先定义"有写权限"的判定（是否以 `requires.fs=true` 为准）。

---

## 12. 实现事实（P0，2026-10-30）

本节记录 P0 的**实际落地结果**，与 §5 的设计意图可能有偏离之处，以本节为准。

### 12.1 落地范围

P0 交付 C1–C7、C5b、C9 与测试 T1–T8、T12、T15、T16。**未做**：C8（`execute_command` 命令族判定 / 能力面剔除）、C10（`task_frontier` writer 视图）、P2 外部锚、§8 的指标与 `event_log` 事件。

### 12.2 文件改动

| 文件 | 类型 | 实际内容 |
|---|---|---|
| `src/llm_loop/core/write_scope.py` | **新增** | `WriteScope` / `parse_write_scope` / `scope_allows` / `intersect_write_scope` / 审计三函数；pattern 上限 64、单条 ≤512 字符 |
| `src/llm_loop/core/execution_surface.py` | 改 | `SurfaceRequirements` 增加 `write_scope` 字段 + `from_kwargs` 解析 |
| `src/llm_loop/core/run_context.py` | 改 | 新增 `current_write_scope: ContextVar[WriteScope \| None]`（默认 None = 全量） |
| `src/llm_loop/workspace/file_service.py` | 改 | `edit()` / `observe()` 接受可选 `write_scope`；越界抛 `FileServiceError(error_type="write_scope_violation")` |
| `src/llm_loop/tools/builtin/edit_file.py` | 改 | 读取 `current_write_scope` 传入 FileService；新 error_type 映射为确定性拒绝回执 |
| `src/llm_loop/tools/builtin/spawn_subagent.py` | 改 | `requires.write_scope` schema；非法 → 既有参数错误链路；透传给 runner |
| `src/llm_loop/subagent/runner.py` | 改 | `_compute_child_write_scope`；**异步 `start()` 与同步 `run()` 两条路径**均注入并在 `finally` 恢复 token |
| `src/llm_loop/tools/builtin/verify_path_scope.py` | **新增** | 只读观测工具：有效 scope / 已写路径 / 越界计数 |
| `src/llm_loop/factory.py` | 改 | 注册 `verify_path_scope` |
| `src/llm_loop/tools/registry.py` | 改 | `verify_path_scope` 工具描述 |

新增测试：`tests/test_write_scope_contract.py` / `tests/test_write_scope_enforcement.py` / `tests/test_write_scope_spawn.py` / `tests/test_verify_path_scope_tool.py`。

> **更正（2026-10-30，详见 §13.8）**：原文写「既有测试零修改」**不成立**——§13.3 为满足 R9 棘轮把 `build_engine` 的基础工具注册抽成模块级 `_register_basic_tools(register_basic)` helper（根因提交 `ab86dde5b`），既有用例 `tests/unit/test_inspect_code.py::test_factory_registered` 断言的是字面量 `_register_basic("inspect_code"`，调用形态变化后该用例变红（2026-10-30 15:33 全量回归实测：1 failed）。本轮按「行为级断言替代字面量断言」修回（§13.8）；除该文件外未改任何既有测试。

### 12.3 实现期偏离设计之处（三处，均为实现期发现）

1. **`SurfaceCapability` 未增加 write scope 维度**（设计 C1 有列）。理由：能力矩阵用于"子端能力 vs 父请求"比对；write scope 是**运行时数据**而非能力位，塞进 capability 会污染既有 5 位语义。改为在 `SurfaceRequirements` 增加字段 + `from_kwargs` 解析，跨版本 fail-closed 改由"父检测子端不识别字段 → 拒绝"承担。
2. **`paths: []` 的只读语义在 C6 与 C7 分层实现**：C6（`FileService`）层对 `paths: []` 一律拒绝**读与写**（fail-closed）；C7（`edit_file`）层**只对写操作**下发 scope，因此只读 child 仍可读文件。二者的取舍是刻意的：C6 管已声明 scope 的强制，C7 管"要不要下发 scope"的决策点。
3. **拒绝位置在同步 `run()` 路径位于 `_reserve_child` 之后**（异步 `start()` 路径在预留之前即返回，与 F2 一致）。同步路径沿用既有 `required_tools` 拒绝的同构位置，拒绝后经 `_finalize_child` 清理，不启动任何 provider / tool 动作。

### 12.4 验收证据

| 项 | 结果 |
|---|---|
| 新增 4 个测试文件 | 父级独立复跑：**141 passed, 1 skipped（2026-10-30 14:36 于返修 + 抽减收尾后的工作树复测；P0 初版实现为 109 passed / 1 skipped）** |
| Ruff（14 个改动文件） | 全绿 |
| 静态诊断棘轮门 | `new=0`，`changed_file_diagnostics=0` |
| RULE-AI-35 实测 | 越界写入被真实拒绝（`write_scope_violation`），目标文件字节未变；scope 内写入正常 |
| 既有测试 | **更正（2026-10-30，详见 §13.8）**：原文「全量回归 12223 passed（子代理回执）」**不成立于最终树**——该数字测于 §13.3 抽 helper 之前。父级在 `566e5b09f` 上独立复跑 `pytest tests/ -q -m "not real_llm and not serial_signal"`：**1 failed, 12254 passed, 155 skipped, 23 deselected（834.89s）**，唯一失败为既有用例 `tests/unit/test_inspect_code.py::test_factory_registered`（根因 `ab86dde5b` 抽 helper），已修；修后数字见 §14。传递链 agent 报告的 `test_idle_timeout_fails_closed` 失败经父级独立复跑 3 次全绿，判为负载相关 flake |

### 12.5 未覆盖与残余（对应 §9）

§9 的 8 条残余逃逸口**在 P0 全部成立**，尤其：模型自声明 ≠ 授权（P0 是护栏 + 取证）；`execute_command` 与 cp / 裸 shell 通道**不经 `FileService`，P0 完全不覆盖**；父会话自身不受约束；未来新增第三条子代理启动路径仍可能漏注入（建议把 scope 注入收敛到单一封装函数）。

---

## 13. RULE-AI-28 独立审查与返修记录

### 13.1 审查结论

首轮独立审查（`review_admission` kind=full_test，冻结产物 SHA `71921c8f…`）判定 **REVISE**：P0=0 / P1=1 / P2=7。P0 无问题；P1 为 `intersect_write_scope` 的 deny ∩ deny 判定错误。

### 13.2 逐条处置

| 审查项 | 判定 | 处置 |
|---|---|---|
| P1-1 `deny ∩ deny` 求交判定错误 | **成立** | 已修：deny 模式的 `paths` 统一解释为**排除集**；deny ∩ deny 结果为 `mode=deny`（排除集 = P ∪ C），排除集之外放行。拒绝原因从误导性的 `not_in_allow_list` 改为 `denied_by_deny_list` |
| P2-1 `{"paths":[],"mode":"deny"}` 全量放行 | **成立** | 已修：`parse_write_scope` 拒绝该组合（返回 None → 走既有参数错误链路） |
| P2-2 审计无 per-child 归属 | 成立（已知边界） | 不在本轮扩范围；P1 候选 |
| P2-3 审计无容量上限 | 成立（已知边界） | 不在本轮扩范围；P1 候选 |
| P2-4 glob 正则回溯 | **过度告警** | 父级实测：`(?:/[^/]+)*` 组内无歧义字符，8/10/12 层 `**` 与多种嵌套 pattern 均在 0.001s 内完成，未触发指数回溯；不修 |
| P2-5 delta 混入无关文件 | **不成立** | 那些 `.tmp-*` / `data/methods/` 是仓库既有的未跟踪文件，与本任务无关；本任务用精确路径 `git add` 隔离，提交范围为 15 个文件，**不含**它们 |
| P2-6 pattern 未归一导致误拒 | 成立 | 已修：pattern 归一（去前导 `./`、尾 `/`、统一分隔符） |
| P2-7 `verify_path_scope` 未区分 allow/deny 语义 | 成立 | 已修：按 mode 标注"允许写入路径"/"排除路径（命中即拒）"，并单列叠加的父链 deny 集 |
| **父级自查新增**：`{"paths":["./"],"mode":"deny"}` 空转排除集 → 全量放行 | **成立** | 已修：deny 模式下归一后为空的 pattern（`./`、`/`、`.`、`""`、`//`）一律**拒绝解析**；allow 模式下归一为空即空允许集 → 拒绝一切写（只读语义） |

### 13.3 架构棘轮门（R9）处理

本次新增功能使 5 个函数体增长，触发 `tests/unit/test_arch_guards.py` 的"棘轮只降不升"断言。**处置原则：先减重，不抬高登记**（`scripts/regen_function_size_baseline.py` 虽可重登记，但 `test_baseline_ratchet_not_raised` 明确禁止；`exemptions` 通道只适用于 `optional|plugin` 类模块，不适用 core 模块的函数行数）。

减重结果：

| 函数 | 登记 | 峰值 | 终值 | 手法 |
|---|---|---|---|---|
| `runner.py::start` | 425 | 458 | **387** | 11 处同构 5 键回执收敛到 `_start_failure_result` |
| `runner.py::run` | 214 | 251 | **208** | write_scope 求交/拒绝/注入逻辑与 `start` 收敛到共用 helper |
| `runner.py::_worker` | — (≥120 需登记) | 132 | **113** | token 注入/恢复抽为共用结构 |
| `factory.py::build_engine` | 2151 | 2153 | **2149** | 新建模块级 `_register_basic_tools(register_basic)`，把 3 条注册（inspect_code / present_files / verify_path_scope）收进 helper |
| `edit_file.py::run` | 68 | 75 | 见 §13.5 | 说明文本外提到模块级 |
| `spawn_subagent.py::execute` | 170 | 196 | 见 §13.5 | `write_scope` 子 schema 与 `requires` description 外提到模块级常量 |

**终值全部 ≤ 登记值，红线未抬高**（`build_engine` 与 `runner.py::run` 反而下降）。

### 13.4 父级独立复验（不采信子代理自述）

| 项 | 方法 | 结果 |
|---|---|---|
| P1-1 修复 | 父级写探针实测 deny∩deny | public 放行 / secret·private 拒绝，原因 `denied_by_deny_list` ✓ |
| P2-1 修复 | 父级写探针 | `empty+deny` → None；`empty+allow` → 只读 ✓ |
| P2-6 归一 | 父级写探针 | `"./src/**"` 与 `"src/**"` 等价 ✓ |
| 空转排除集 | 父级写探针枚举 5 种 pattern | deny 模式全部拒绝解析；allow 模式全部 fail-closed ✓ |
| FR-6 glob 边界 | 父级写探针 | `src/**` 命中 `src/a/b.py`；`src*` 不命中 `srcevil/x.py` ✓ |
| ContextVar 无泄漏 | 父级写探针 | reset 后回到 None ✓ |
| 只读 scope | 父级写探针 | 写入被拒、字节未变 ✓ |
| scope 内外混合 | 父级写探针 | 内放行、外拒绝、字节未变 ✓ |

### 13.5 抽减收尾（已完成，父级独立复验）

抽减 agent 的两文件重构已完成，父级在**暂存后**独立复验（棘轮守卫有双口径：未暂存时按 HEAD 读，暂存后按工作树读）：

| 函数 | 登记 | 重构前 | 终值 | 手法 |
|---|---|---|---|---|
| `edit_file.py::run` | 68 | 75 | **68** | 新增模块级 `_current_scope_kwargs()`，4 行 C7 注释原文搬入其 docstring；`workspace_scope` 与 `write_scope` 两行合并为 1 行 `**_current_scope_kwargs()` |
| `spawn_subagent.py::execute` | 170 | 196 | **164** | 新增模块级常量 `_REQUIRES_SHAPE_ERROR` 与 helper `_parse_requirements()` / `_required_write_scope_kwargs()`；两条 DESIGN 注释原文搬入 docstring |

**schema 等价性（父级独立证明，非采信子代理哈希）**：父级用 `git show HEAD:` 取重构前版本单独 import，对比 `parameters` 的 `json.dumps(sort_keys=True)` 哈希：

| 对象 | 结果 |
|---|---|
| `spawn.parameters` | OLD `4e081f14dbde7c5debfb` == NEW `4e081f14dbde7c5debfb`，`EQUAL: True` |
| `edit.parameters` | OLD `45dc87b69d29241b122e` == NEW `45dc87b69d29241b122e`，`EQUAL: True` |
| `requires.description` 全文 | `EQUAL: True` |
| `requires.write_scope` 子对象 | `EQUAL: True` |
| `requires` 键集合 | `EQUAL: True` |

`parameters` 是**类属性**（不计入函数体行数），故 schema 本身零改动——等价性比"搬移后重新拼装"更硬。

**棘轮门终态**：`tests/unit/test_arch_guards.py` **40 passed 全绿**；6 个受影响函数终值全部 ≤ 登记值，`build_engine`（2149 < 2151）与 `runner.py::run`（208 < 214）反而下降，红线未抬高。

### 13.6 已知工具链事实（本次踩到，值得记录）

`tests/unit/test_arch_guards.py` 的棘轮守卫按 **`git show HEAD:`** 读取被测文件：文件已暂存（`M `）时读工作树，**仅工作树改动（` M`）时读 HEAD**。因此任何"减重"修复在 `git add` 之前，守卫仍会按旧 HEAD 判定为失败——这是**双口径**，不是回归。已由抽减 agent 定位并记录为 experience。



### 13.7 第三轮准入（git_push 门禁）P1 与处置

`review_admission` kind=git_push（候选 SHA `077801fb…`）判定 **REVISE**：P0=0 / **P1=1** / P2=3。

- **P1（文档快照相对已提交测试过期）**：被审文档快照止于 §12.5——§12.4 仍写「父级独立复跑：109 passed, 1 skipped」，且整节 §13（本次独立审查与返修记录）不在快照内；而同一快照内已提交的测试文件已含返修补测。
- **处置**：① §12.4 的复跑数字更新为 **141 passed, 1 skipped**（2026-10-30 14:36 于返修 + 抽减收尾后的工作树复测；4 个测试文件 = `tests/test_write_scope_contract.py` + `tests/test_write_scope_enforcement.py` + `tests/test_write_scope_spawn.py` + `tests/test_verify_path_scope_tool.py`）；② §13 整节随本次提交入库，使「文档记录的返修」与「已提交的返修代码 / 测试」落在同一快照。
- **P2（非阻断，本轮未修）**：已核实原文的 P2-3 为 glob 引擎把字符类编译成 `[^x]` 形式，可跨 `/` 命中（如 pattern `a[!x]c` 匹配路径 `a/c`），与模块 docstring「字符类不支持跨段」有出入；影响限于已在 realpath 检查过的 workspace root 内的过宽匹配，安全相关边界仍 fail-closed。其余 P2 条目未逐条转录，不在此臆述。

### 13.8 第四轮（接管会话）独立复验：发现并修复既有测试回归

接管会话在 `566e5b09f`（本 Goal 已推 `origin/main`）上做**父级独立复验**（不采信前序子代理自述），发现 §12.4「既有测试全量回归通过」与 §12.2「既有测试零修改」两处陈述与最终树不符。

**复验事实**

| 项 | 实测结果 |
|---|---|
| 复跑命令 | `PYTHONPATH=src .venv/bin/python -m pytest tests/ -q -m "not real_llm and not serial_signal"`（2026-10-30 15:18 起，15:33 结束） |
| 结果 | **1 failed, 12254 passed, 155 skipped, 23 deselected（834.89s）** |
| 唯一失败 | `tests/unit/test_inspect_code.py::test_factory_registered` — 断言字面量 `_register_basic("inspect_code"` 在 `src/llm_loop/factory.py` 中不存在 |
| 根因 | §13.3 的减重手段：提交 `ab86dde5b` 把 `build_engine` 内联的三条基础工具注册抽成模块级 `_register_basic_tools(register_basic)` helper，调用形态由 `_register_basic(...)` 变为 `register_basic(...)`；**该用例是既有守卫**，其字面量断言未随重构更新 → 回归 |
| 责任归属 | 本特性改动一侧（重构改了既有守卫依赖的调用形态），不是环境或 flake |

**处置（先查职责问题，不抬 baseline、不加豁免、不改 `src/`）**：守卫变红属「实现改形态、守卫未同步」，因此改的是**既有用例的断言方式**而非放宽守卫：

| 处置项 | 内容 |
|---|---|
| 断言升级 | 字面量断言 `_register_basic("inspect_code"` → **行为级断言**：直接调用 `factory._register_basic_tools(register_basic)` 收集注册表，断言 `inspect_code` 在册且实例为 `InspectCodeTool`；并断言 `build_engine` 源码仍把基础注册回调交给该 helper（接线未丢） |
| 守卫语义 | 不变——`inspect_code` 必须走 factory 基础工具注册路径；新断言**强于**原字面量断言（原断言不校验注册内容与接线） |
| 改动面 | 仅 `tests/unit/test_inspect_code.py` 一个文件；`src/` **零改动** |
| 未做 | 未抬高任何棘轮登记、未加豁免、未改实现、未改其他既有测试 |
| 复验 | 该文件 **9 passed**；write_scope 4 文件 + `tests/unit/test_arch_guards.py` **181 passed / 1 skipped**；`scripts/check_static_diagnostics.py --tool ruff` **PASS（new=0，changed_file_diagnostics=0）** |
| 待办 | 修后全量回归数字与最终准入结果见 §14（第二轮 RULE-AI-28 准入） |

**诚实边界**：本节只能证明「该既有用例的失败被定位并修回」；§12.4 中「12223 passed」这一历史数字**仍然不适用于最终树**，已在该行就地标注更正，不删改历史记录。

## 14. 最终验收与交付说明（2026-10-30 15:40，接管会话）

本节是本 Goal 的**交付说明**：变更清单、测试证据、准入回执、残余逃逸口、诚实边界（未做什么）。所有数字均为本会话实测或工具回执，不采信前序子代理自述。

### 14.1 变更清单

| 提交 | 内容 | 归属 |
|---|---|---|
| `ab86dde5b` | write_scope P0 实现收口（core/tools/workspace/runner + 4 个测试文件 + 设计文档 + phase3-6 验收产物） | 前序会话 |
| `038a0821e` | 并发写者收尾：§13 返修记录入库 + R9 棘轮减重（`build_engine` 抽 `_register_basic_tools` helper） | 前序会话 |
| `566e5b09f` | 归档后续状态与残余逃逸口说明（已推 `origin/main`） | 前序会话 |
| `bfeacf003` | **修回既有守卫** `test_factory_registered`（§13.8）+ §12.2/§12.4 陈述更正 + VERIF 补记 | 接管会话 |
| `（本提交）` | §14 交付说明 + 接线检查升级为 **AST 调用判定**（独立审查 P2-3）+ 交接文档 §9 补记 | 接管会话 |

### 14.2 测试证据（分层，各自标注口径）

| 层 | 命令 / 来源 | 结果 |
|---|---|---|
| 特性测试 | `pytest tests/test_write_scope_{contract,enforcement,spawn}.py tests/test_verify_path_scope_tool.py` | **141 passed / 1 skipped**（2026-10-30 14:36，返修 + 抽减后工作树） |
| 聚焦复验 | 同上 4 文件 + `tests/unit/test_arch_guards.py` | **181 passed / 1 skipped**（15:34） |
| 既有守卫复验 | `pytest tests/unit/test_inspect_code.py` | **9 passed**（15:34，含本轮修回用例） |
| 静态诊断 | `scripts/check_static_diagnostics.py --tool ruff` | **PASS**（new=0，changed_file_diagnostics=0；15:33 / 15:38） |
| RULE-AI-35 实测 | `scripts/verification/write_scope_gate_probe.py` | **9/9 PASS, exit 0**（15:20，最终树）：越界写入被拒、目标字节不变、无半成品、symlink/`..`/deny/observe 各分支均覆盖 |
| 全量回归（**修前**） | `pytest tests/ -q -m "not real_llm and not serial_signal"`（HEAD `566e5b09f`） | **1 failed, 12254 passed, 155 skipped, 23 deselected（834.89s）**——失败即 §13.8 的既有守卫回归 |
| 全量回归（**修后**） | 同口径，最终树 | 见 §14.5 |

### 14.3 独立审查与准入回执（RULE-AI-28）

| 准入 | 目标 | 候选 | 结论 |
|---|---|---|---|
| `review_admission` kind=full_test | `bash scripts/ci_gate.sh`（本仓 canonical 全量门禁） | `7ba48414…`（child `subagent_b728459b392d`） | **PASS（P0=0 / P1=0 / P2=3）** |
| `review_admission` kind=full_test | 同上，最终树（含本提交） | 见 §14.5 | 见 §14.5 |
| `review_admission` kind=git_push | 推送前最终树 | 见 §14.5 | 见 §14.5 |

**P2 处置（本轮）**

| P2 | 内容 | 处置 |
|---|---|---|
| P2-1 | §13.8 出现 §14 悬空前向引用 | 本节补齐 §14，引用闭合 |
| P2-2 | 未跟踪 `.tmp-*` 过程脚本含本机绝对路径（`/Users/…`） | **未提交、未删除**（属他人过程物）；如实登记于本节与交接文档 §9 |
| P2-3 | `build_engine` 接线检查是源码子串断言，可被注释满足 | **已修**：改为 `ast.parse` 后判定确有 `_register_basic_tools(...)` 调用 |

### 14.4 残余逃逸口（**未闭环**，明确列出）

- **`execute_command` / 裸 shell 通道（C8 未实现）**：写侧 scope 只约束走 `FileService` 的写入；不经该路径的 shell 写入**运行期无法完全阻断**，只能事后检出归因（§9 / §12.5）。
- **`cp` / 外部复制等旁路**：同理，不在 P0 约束面内。
- **其他未改造的写入口**：本轮只覆盖 `FileService` + `edit_file` + 子代理传递链；未做全仓写入口普查（下一期入口见交接文档 §5）。
- **glob 字符类跨段语义（P2-3，历史遗留）**：pattern `a[!x]c` 可命中 `a/c`，与模块 docstring「字符类不支持跨段」有出入；影响限于已过 realpath 检查的 workspace root 内过宽匹配，安全边界仍 fail-closed。**本轮未修**。

### 14.5 最终验收结论

（由接管会话在本节最后一次编辑时填入：修后全量回归数字、最终 full_test 准入与 git_push 准入回执、推送结果。）

### 14.6 诚实边界（未做什么 / 不能声称）

1. **C8 未全量实现**：P0 段（命令串绝对路径字面量 scope 校验 + `scope_unverified` 审计事件）仍未做——shell 通道本身仍不受写侧 scope 约束；**P1-b 段（能力面剔除）已于 §15 落地**。仍不得声称「写侧路径授权已全量生效」。
2. **P1-b 能力面剔除**（受限 child 不给 `execute_command`）：本条原写「未实现，不在本次交付范围」——**已于 §15 落地**（受限 child 启动时剔除 `execute_command` 工具面；父子均未声明 write scope 时工具面零变化）。
3. **未改任何既有守卫的门槛**：本轮唯一改动的既有文件是 `tests/unit/test_inspect_code.py`，且是把字面量断言**升级**为行为级断言，未放宽任何断言。
4. **未清理他人过程物**：仓库根 `.tmp-*` 与 `reports/qualification-r4/mech-all-sample.json`（1.28MB）仍未入库、未删除。
5. **前序子代理自述未被采信**：本会话对 §12.4 的「12223 passed」做了独立复跑并发现其不适用于最终树（§13.8）；文档中的历史数字**就地标注更正**而非删改。
6. **本会话派出的只读审计子代理失败**（上下文预检拒绝截断，结论未产出），其结论未被采纳；相关核查改由父级定向执行（grep + 实测），证据见 §14.2。
7. **全量回归口径**：§14.2 的父级复跑口径为 `-m "not real_llm and not serial_signal"`（23 个 serial_signal 用例未纳入父级复跑）；RULE-AI-28 准入走 `scripts/ci_gate.sh` 的 canonical 口径（不排除 serial_signal），两者口径不同，**不可互相替代**。

## 15. P1-b 能力面剔除落地（2026-10-30 15:4x，本会话）

### 15.1 触发与口径

§9 的 P1-b 需要产品口径决定「受限写域的 child 是否自动失去 `execute_command`」。本轮口径：**直接剔除**（不走 P1-a 命令族改写）——受限写域的 child 启动时工具面里就没有 `execute_command`，其余工具一个不动。

### 15.2 落点：为什么这是程序级拦截，不是提示层建议

工具面由同一个 ContextVar `current_tool_discovery_scope` 驱动四处：child 的**模型可见工具 schema**（`runner.py` 按 scope 过滤）、工具目录列举、`call_tool` 按名派发、以及**越权直调拦截**（`E1_TOOL_WHITELIST`）。剔除落在 scope 变量上 → 四处同时生效，模型即使凭空点名 `execute_command` 也会被程序拒绝。

判定函数 `SubAgentRunner._restrict_tool_surface_for_write_scope`：**受限** = `child_write_scope` 非 None 且 `declared=True`（显式声明，含 `paths:[]` 显式只读）；父声明、子未声明 → 继承父 scope，同样受限；父子都未声明 → 工具面零变化。

### 15.3 两条路径同款（不做单路径补丁）

| 路径 | 落点 |
|---|---|
| 异步 `start()` | 写域裁决之后、预留 child 资源之前剔除；回执新增可选字段 `write_scope_tool_restriction`（仅在发生剔除时出现） |
| 同步 `run()` | 同一判定函数；未声明 `requires.tools` 时按继承语义取当前 scope 再剔除，必要时把 registry 名单物化为 child 工具面（去掉 `execute_command`） |

### 15.4 这条比 P0 的字面量校验更硬

实测 `execute_command.py` 不读 `write_scope`（全仓 grep：仅 `edit_file.py` 与观测面 `verify_path_scope.py` 消费 `current_write_scope`）→ 命令通道的写侧约束此前**只存在于文档层**。P1-b 落地后，受限 child 根本没有命令工具，剩余写入口 `edit_file` 受 scope 强制 → 绕过面从「命令族语义盲区」降为「不可用该工具」。

### 15.5 测试与准入

| 项 | 结果 |
|---|---|
| 新增用例 | T17–T23（见 §12.2 表），落 `tests/test_write_scope_spawn.py::TestP1bToolSurface` |
| 聚焦复跑 | `pytest tests/unit/test_review_host_admission.py tests/test_write_scope_spawn.py tests/unit/test_arch_guards.py` → **220 passed** |
| 门禁自证伪 | 把判定函数打成空实现后重跑：**6/7 用例红**（T19 零回归用例仍绿）——证明新用例在测拦截，不是空转 |
| 静态诊断 | `ruff check`（4 个改动文件）→ 干净 |
| RULE-AI-28 准入 | `review_admission(kind=full_test)` → **PASS**（child `subagent_3656c03e6e48`，候选 SHA `8cc08855…`） |

### 15.6 诚实边界

1. **P1-b 有真实代价**：受限 child 连只读命令（`ls`/`git log`/跑测试）也不能执行——这是本口径的已知代价（§9 已记），不是 bug。
2. **C8 的 P0 段仍未做**：命令串绝对路径字面量校验 + `scope_unverified` 审计事件未实现；本节只关闭 P1-b。
3. **不声称「写侧路径授权已全量生效」**：`cp` 等旁路仍在 P0 约束面之外（§14.4）。
4. **并发写者**：本节落地时仓库内有另一活跃会话（`cbda67c5-…`，非本会话子代理）在同一工作树活动；本节只提交本轮 5 个文件，其过程物与他人改动未纳入、未删除。
