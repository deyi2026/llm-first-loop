# 需求实施设置：write-scope 内核化 与 StateBraid 缓存正确性/定价

> 文档日期：2026-10-31
> 涉及仓库：`~/Project/llm-first-loop-mirror`（主）、`~/Project/research/StateBraid`（外部工作区）
> 状态：**需求草案，未实施**
> 事实基线：本文行号与符号取自 2026-10-31 当前文件状态，**未固定 commit**。实施前须以 `git rev-parse HEAD` 记录基线，行号漂移时以符号名为准。
> 修订：v3（新增 §9.1 决策登记、§9.2 冲突记录；规则 D/E 补可判定条件。v2：补 deny 语义、可编译形态判定与跨平台大小写，见 §8 B4/B8/B9/B10）

---

## 0. 定位与非目标

### 0.1 本文档要解决的问题

两条判断，同一个形状：**继续在同一层加参数，边际收益已低于维护成本，应当换一层承担职责。**

- write-scope：两天 25 轮，仍在为第 N 个命令族建模选项语义。
- StateBraid：驱逐策略缺"重算成本"这一维，导致按年龄逐出最长条目。

### 0.2 非目标（明确不做）

| 不做 | 理由 |
|---|---|
| 不再为 `command_scope_guard` 新增命令族语义 | 开放集合不可穷尽；见 §7 规则 A |
| 不在 StateBraid 内引入更多语义角色 | 与 README 明文立场冲突；见 R6 |
| 不把本改造宣传为"沙箱加固" | 网络未隔离、读未限制（`~/.ssh`、`.env` 可达）；见 §5.4 |
| 不在本文档内承诺性能收益 | 成本定价是待实测假设，非已证结论 |
| 不修改 `EXEC_SANDBOX_MACOS_WRITABLE` 既有语义 | 宿主显式配置面，只增加 per-call 维度 |

---

## 1. 事实基线（已核实 / 未核实）

### 1.1 已核实（附证据位置）

| # | 事实 | 位置 |
|---|---|---|
| F1 | `check_command_scope(command, *, scope, workspace_root, workdir)` 为命令写侧判定入口；`scope=None` 或 `declared=False` 恒放行 | `core/command_scope_guard.py:2791-2803` |
| F2 | `command_scope_guard.py` 2808 行；`write_scope.py` 515 行 | 实测 `wc -l` |
| F3 | `WriteScope` 用 **glob** 语义判定（`_matches` / `_pattern_regex` / `_translate_segment`，`\Z` 锚定） | `core/write_scope.py:66,105,143,178` |
| F4 | `scope_allows(scope, abs_path, workspace_root) -> (bool, str)` | `core/write_scope.py:314` |
| F5 | `sandbox_argv(command, workdir, *, mode, image)` **不接收**可写根参数 | `tools/sandbox.py:294-300` |
| F6 | `sandbox_exec_argv(command, workdir, *, writable_roots=())` **已接收**可写根 | `tools/sandbox.py:286-291` |
| F7 | `macos_writable_roots(workdir, *, extra=())` **已有** `extra` 通道，并读 `EXEC_SANDBOX_MACOS_WRITABLE` | `tools/sandbox.py:250-274` |
| F8 | sandbox-exec profile：`(deny file-write*)` + 逐条 `(allow file-write* (subpath ...))`，**前缀语义** | `tools/sandbox.py:277-283` |
| F9 | sandbox-exec 默认可写根 = 工作区 + `/tmp` + `/private/tmp` + `/dev` + `~/.cache` + `~/Library/Caches` + `~/.npm` | `tools/sandbox.py:256-264` |
| F10 | `bwrap_argv` / `docker_argv` **均不接收**路径集合 | `tools/sandbox.py:204,220` |
| F11 | 唯一 `sandbox_argv` 调用点 | `tools/builtin/execute_command.py:803` |
| F12 | sandbox-exec **只约束写**；不隔离网络、不限制读 | `docs/EXECUTION-ISOLATION.md:95-104` |
| F13 | `EXEC_SANDBOX` 默认 `auto`；darwin 顺序 sandbox-exec → docker → none；落到 none 非 strict 时放行并告警 | `docs/EXECUTION-ISOLATION.md:66-83` |
| F14 | `plan_admission` 对 `nbytes > max_bytes` 直接返回 `oversized` 拒收 | `cache/policy.py:249-250` |
| F15 | `plan_trim(n_sequences, n_bytes)` 存在，但作用于**已缓存条目**，不处理单条超预算 | `cache/policy.py:352-382` |
| F16 | `_next_victim` 取"角色排名最低 + 桶内插入序最早"者，**不读 nbytes** | `cache/policy.py:433-443` |
| F17 | `_oldest_pin` 同理，按 rank 升序 + 桶内 FIFO | `cache/policy.py:445-454` |
| F18 | 整个 `cache/policy.py` 无 cost / benefit / reuse-value 维度 | grep 仅命中 `pin_count` |
| F19 | `ensure_generation_safe_exact_hit` 仅保证"生成至少收到一个 token" | `cache/generation.py:11-37` |
| F20 | `is_generation_safe_hybrid_checkpoint` 要求 hybrid 状态恰好 `N-1` 前缀 | `cache/generation.py:40-42` |
| F21 | `src/` 内除 `@property` 假阳性外，**无** offset / `position_ids` / `n_past` / rope 处理 | `grep -v property` 命中 0 行 |
| F22 | `tests/` 内无 logits 或 canary 数值比对用例 | `grep -rln 'logits\|canary' tests/` 返回空 |
| F23 | StateBraid README 明文：语义标签不获得默认缓存优先级或 pin 权限 | `StateBraid/README.md` |
| F24 | companion `PIN_TAGS = {"goal","evidence","identity","rules"}` 并做分级 | `mlx-lm-statebraid-companion/cognitive_cache.py:58,61-72` |
| F25 | `WriteScope` 有 `mode` 二态：`allow`（`paths`=允许集）/ `deny`（`paths`=**排除集**，空排除集=全量放行，parse 层确定性拒绝该组合） | `core/write_scope.py:67-83` |
| F25b | **deny 条目带目录语义**（D1 修复）：非 `/**` 结尾的 deny 条目在解析层存储为 `p + "/**"`。因 `X/**` 的命中集 = `{X} ∪ {X 下任意层}` 且本身命中 `X`，故对文件目标与 `p` 等价（`deny ["a.txt"]` 仍排除 `a.txt`），对目录目标从"只排除目录自身（写目标永不命中）"收紧为"排除整棵子树"。方向恒为更严格；allow 模式不受影响；`**` 与已带 `/**` 者原样 | `core/write_scope.py:_expand_deny_pattern`；`tests/test_write_scope_contract.py::test_deny_bare_directory_name_excludes_whole_subtree` |
| F26 | `deny_paths` **优先于** `paths`；`scope_allows` 判定序 = root 边界 → deny → allow | `core/write_scope.py:339-350` |
| F27 | `_cmp` 仅在 darwin 大小写不敏感时 casefold，其余平台不折叠 | `core/write_scope.py:89-91` |
| F28 | `_covered_by` 对 glob-in-glob 采保守判据："不可证明即不覆盖" | `core/write_scope.py:363-387` |
| F29 | `intersect_write_scope` 的 deny 分支把子 deny 叠加进 `deny_paths`，**不**降级为 allow+空集 | `core/write_scope.py:397-404` |

### 1.2 未核实（实施前必须消除）

| # | 未核实项 | 影响 | 消除方式 |
|---|---|---|---|
| U1 | 两仓库 commit 基线 | 行号漂移 | `git rev-parse HEAD` |
| U2 | llama.cpp **managed** 路径能否按 token 数捕获/截断（MLX `KVCache` 支持 trim 已确认） | 决定 R5 是否仅 MLX 可行 | 读 adapter + 最小复现 |
| U3 | bwrap / docker 增加 per-call 路径集的实际可行性与开销 | 决定 §4 矩阵是否成立 | 各跑最小验证 |
| U4 | 复用路径与全量 prefill 的 logits 抖动基线 | 决定 R3 阈值 | 先测同路径重复性 |
| U5 | `bytes/token = 300,902`（27B fp16）是否可泛化 | 影响 R5 换算 | 按模型重测 |
| U6 | `plan_trim` 的既有调用方与频率 | R5 是否与既有 trim 冲突 | grep 调用点 + 单测 |
| **U7** | **Seatbelt `(subpath "/path/to/file.py")` 是否精确匹配单个文件** | 决定文件级 scope 能否直译 | 实测一条 profile |
| **U8** | **SBPL deny/allow 的优先级规则（last-match-wins）与 `deny` 优先是否一致** | 决定 deny 语义能否用内核表达 | 实测 |

---

## 2. 需求清单

优先级依据：**先修"静默给错结果"，再修"效率"，最后修"可归因"**。

### R1（P0）write-scope 停止规则

**现状**：里程碑已到"第二十五轮 — 第九轮独立审查响应"；55 次相关提交集中在两天；每轮新增命令族选项建模。

**需求**：设立可判定的换向触发条件，避免继续在开放集合上做封闭建模。

**验收标准**
- [ ] 停止规则写入仓库文档，且可被第三方按提交历史客观判定
- [ ] 第 26 轮若新增命令族，必须**先**回答"为何不换层"，写入评审记录
- [ ] 判定口径明确：diff 中出现新的命令族分支或命令名常量即为"新增"

**已知边界**：治理约束，无法由测试断言。

---

### R2（P1）write-scope 强制点内核化

**现状**：静态解析是唯一防线；`_unmodeled_construct` 对 `$()`、反引号、进程替换、花括号分组、控制流关键字一律 fail-closed；shell 内 `python -c`、`sh script.sh`、`find -exec` 对解析不可见。
（**2026-10-31 D2 修订**：heredoc 与未加引号的 `( … )` 不再整体拒——正文按 stdin 数据剥离、分组内部逐条递归判定；前提是先删续行（`\`+换行）再切逻辑行 + 原始串级执行向量先拒 + 分隔符按 bash **词级引号移除**读取 + 跨行引号/算术深度状态维护 + 空分组拒 + `$`/`~`/反引号等展开形态直接拒 + `(( … ))` 内 `<<` 与 `<<<` 整体拒，读不出即拒。25 条既有绕过向量复测仍 25/25 拦（**仅限所列向量**；delimiter 引号形态、跨行引号、展开形态、算术/here-string 上下文、续行由四轮 REVISE 返修补齐，见 `REPORT-20261031` §10.2/§10.5）。）

**需求**：把"不得越界写"的**硬保证**下沉到内核，静态解析转为**纵深防御的一层**，承担"减少攻击面"与"给用户可读理由"。

#### C1（约束）glob → subpath 的可编译形态

`WriteScope` 是 glob（F3），Seatbelt `subpath` 是前缀（F8）。**未经判定不得直译**，否则放大授权。

| pattern 形态 | 字面前缀 | 判定 | 说明 |
|---|---|---|---|
| `X/**` | `X` | **可编译（等价）** | scope 亦允许 `X` 目录本身，放行面一致 |
| `X/Y/**` | `X/Y` | **可编译（等价）** | 同上 |
| `X`（无通配） | `X` | 可编译但**略放大** | subpath `X` 放行其整个子树，scope 仅该路径；须登记 |
| `X/**/Y` | `X` | **放大，须登记** | subpath `X` 放行全子树，scope 仅 Y |
| `X*`（段内通配） | 空 | **不可编译 → fail-closed** | 首段即含通配，无安全前缀 |
| `**/Y` | 空 | **不可编译 → fail-closed** | 同上 |

**规则**：字面前缀 = pattern 中第一个含通配符段之前的路径；为空则不可编译。

#### C2（约束，本修订新增）deny 语义的不可表达性

`WriteScope` 有两种模式（F25）：`allow`（paths=允许集）与 `deny`（paths=**排除集**）。`deny_paths` 优先于 allow（F26）。

`subpath` 只能**加**不能**减**。因此：

- **allow 模式的放大方向是"多给权限"**：可登记、可接受。
- **deny 模式的放大方向是"该禁的没禁"**：属于**安全回退**，且不表现为报错，极难察觉。

**处置**
- `mode=allow` 且 `deny_paths` 为空 → 按 C1 编译。
- `mode=allow` 但有 `deny_paths` → 需 allow 白名单 + 精确 deny；若任一 deny 项不可转 subpath（U8 未决），**整条 scope 降级为不内核化**（保持静态解析 hard），不得只放行 deny 的可表达部分。
- `mode=deny` → **默认不纳入内核化**（保持静态解析 hard）。理由：其语义是"工作区几乎全开 + 排除若干"，任何排除项失效即等于全开。
- 任何降级必须在回执中如实标注"本命令未启用内核写域约束"，不得沉默。

#### 验收标准
- [ ] 对每个 pattern 生成 ≥20 条采样路径，断言：`scope_allows(p)==True` ⇒ `sandbox_allows(p)==True`（**不得出现声明允许但内核拒绝**，否则是功能回退）
- [ ] 反向采样：`sandbox_allows(p)==True` 且 `scope_allows(p)==False` 的路径全部登记为"授权放大"，每条有显式处置（接受 / 改为 fail-closed）
- [ ] 可编译形态表（C1）逐行有用例，含 `X/**` 等价性正例与 `X/**/Y` 放大反例
- [ ] `mode=deny` 与含 `deny_paths` 的 scope 走用例，断言**不**被内核化且回执标注
- [ ] `uncompilable_patterns` 非空时默认 fail-closed（`WRITE_SCOPE_STRICT=1`），不得静默退化为 workdir 全开
- [ ] 内核化生效时回执 note 写明实际后端与可写根数量（不宣称未实现的能力）
- [ ] `EXEC_SANDBOX_WRITE_SCOPE=off` 时行为与当前**逐字节一致**（零回归）

#### 已知边界
- SBPL 无 glob，`**` 只能近似
- bind-mount 对"写符号链接指向外部"依赖内核 realpath 顺序，需单测锁定
- docker 路径下 daemon 权限仍是绕过面
- sandbox-exec 依赖 macOS 私有接口，长期稳定性有外部风险
- 大小写：darwin `_cmp` casefold（F27），Linux 路径大小写敏感 → **同一 scope 在两端可写面不同**，须在矩阵中标注
- write scope 声明"路径"，沙箱约束"进程"：同进程派生子进程受同一 profile 约束（是优点），但无法区分"哪个子命令写的"

---

### R3（P0）位置一致性 canary

**现状**：`generation.py` 处理"**能否生成**"（非空输入、hybrid N-1），**不处理"位置是否正确"**（F19-F21）。`tests/` 无数值比对（F22）。

**需求**：锁死"复用路径与全量 prefill 数值等价"这条隐含契约。

**原因**：全部需求中唯一"静默给错结果"的风险面；其余只影响效率。

**验收标准**
- [ ] 同一 prompt 两路逐位比对：`full_prefill` vs `prefix_reuse(k)`，`k ∈ {0, 1, n-2, n-1}`
- [ ] 断言：`logits[k]` 最大绝对差 < 阈值，且 top-1 token 一致
- [ ] 阈值先由**同路径重复运行**抖动基线确定（U4），不得拍数
- [ ] 小模型、几十 token 可跑（目标 <60s）
- [ ] 覆盖：标准 MHA 前缀、sliding-window 边界、hybrid N-1（若后端支持）
- [ ] 失败信息含具体位置点 `k` 与偏差量

**已知边界**：若后端使 `k=n-1` 不可表达，该点标 `skip` 并记录原因，不得伪造通过。

---

### R4（P1）驱逐引入重算成本维度

**现状**：`_next_victim` / `_oldest_pin` 只看角色排名与插入顺序，不读 `nbytes`（F16-F18）。A/B 中 2000 tok 的 `goal` 被按年龄先逐出，1500 tok 的 `evidence` 存活，复用率 0% / 100%。

**需求**：让 victim 选择感知"重算这条要花多少"。

**定价模型（假设，待实测）**
```
recompute_cost(entry) ≈ Σ over prefix (α·n + β·n²)
交叉点：n ≈ d_ff ≈ 4d   ← 不是文章原判据的 n ≈ d
```

**验收标准**
- [ ] 先以 `STATEBRAID_EVICTION_COST=shadow` 上线：**只记录**建议 victim，不改变行为
- [ ] shadow 输出对照：实际 victim / 成本建议 victim / 两者 nbytes 与 token 数差
- [ ] 仅当 shadow 数据支持"减少重算 token 总量"才允许切 `on`
- [ ] `on` 时 `off` 一键回滚，且回滚不丢缓存状态
- [ ] 单测：成本相同时回退到既有 rank+FIFO（保证确定性）

**已知边界**：`bytes ∝ n` 线性，attention 二次；只用 `nbytes` 作代理会**低估**长条目，等于没改。必须同时使用 `len(key.tokens)`。

---

### R5（P1）oversized 条目降级为前缀，而非整条拒收

**现状**：`plan_admission` 对 `nbytes > max_bytes` 直接 `reject("oversized")`（F14）。A/B 中 budget=512MB 时 602MB 条目全拒，14 次捕获全 drop，resident 0。

**重要修正**：`plan_trim` **已存在**（F15），本需求**不是**新增 trim 机制，而是**只改 `oversized` 分支处置**。

**需求**：预算不足时按 token 截断为前缀条目，标记 `trimmed`。

**换算示例（基于 U5 待复核）**：`bytes/token ≈ 300,902`，512 MiB ≈ 1783 tok；2000 tok 可保住 ~89%。

**验收标准**
- [ ] `STATEBRAID_OVERSIZED_POLICY=reject`（默认）行为不变
- [ ] `=prefix`：`n_keep = floor(max_bytes / bytes_per_token)`；`n_keep < 1` 仍拒收
- [ ] 截断后 key 必须是原 key 的严格前缀，且通过 `matched_prefix_key` 校验
- [ ] 截断条目不得与同 key 完整条目并存（避免重复计费与误命中）
- [ ] 命中统计区分 `full` / `trimmed`，复用率不得混算
- [ ] 若 U2 结论为 managed 不支持 token 级捕获，则**仅 MLX 路径启用**，文档与回执如实标注

**已知边界**：截断条目对超过 `n_keep` 的前缀无效，可能"看似命中实则短命中"，必须在回执区分。

---

### R6（P2）语义立场归口

**现状**：`StateBraid/README.md` 否认语义优先（F23）；companion `PIN_TAGS` 分级（F24）。两套互斥策略并存。

**需求**：二选一，不得并存无标注。

**验收标准**
- [ ] 二选一：(a) companion 归档为"已放弃的语义路线，保留为反例"；(b) 移入独立目录并标注"不可与 StateBraid 组合"
- [ ] `research/` 下不再存在两套对立策略且无标注
- [ ] 复用率对比文档不得同时引用两套策略数据作同一结论

**已知边界**：治理动作，无技术验证手段；是"能否归因"的前提。

---

## 3. 设置项（配置面）

新增设置一律**默认关闭**，保证零回归上线。

| 变量 | 取值 | 默认 | 作用 | 回滚 |
|---|---|---|---|---|
| `EXEC_SANDBOX_WRITE_SCOPE` | `off` / `shadow` / `on` | `off` | `shadow`=计算并记录将放行的根，不改变 argv；`on`=按 scope 生成可写根 | 置 `off` |
| `EXEC_SANDBOX_WRITE_SCOPE_STRICT` | `0` / `1` | `0` | `1` 时 `uncompilable_patterns` 非空即拒执行 | 置 `0` |
| `EXEC_SANDBOX_WRITE_SCOPE_DENY` | `off` / `shadow` | `off` | deny 形态 scope 是否参与（`shadow`=只记录，不改变行为）；**不提供 `on`** | 置 `off` |
| `STATEBRAID_EVICTION_COST` | `off` / `shadow` / `on` | `off` | `shadow`=只记录建议 victim | 置 `off` |
| `STATEBRAID_EVICTION_COST_ALPHA` | float | 待定 | 线性项系数 | 置 `off` |
| `STATEBRAID_EVICTION_COST_BETA` | float | 待定 | 二次项系数 | 置 `off` |
| `STATEBRAID_OVERSIZED_POLICY` | `reject` / `prefix` | `reject` | 见 R5 | 置 `reject` |
| `STATEBRAID_CANARY_MODEL` | 模型标识 | 无 | canary 用的小模型 | 不设即 skip（不得静默通过） |

**不变项（明确保持）**

- `EXEC_SANDBOX_MACOS_WRITABLE`：语义不变，仅作 `extra` 追加，与 per-call 根**取并集**
- `EXEC_SANDBOX` / `EXEC_SANDBOX_STRICT`：语义不变
- `plan_trim` 调用点：语义不变

**优先级规则**：per-call 根与 `EXEC_SANDBOX_MACOS_WRITABLE` 冲突时取**并集**（不静默收紧宿主显式配置）；需要收紧时由 scope 声明，不靠环境变量。

**为什么 `WRITE_SCOPE_DENY` 没有 `on`**：deny 模式下内核表达的失败方向是"该禁的没禁"（见 §5.5），且无可靠的自检手段。故只允许 `shadow` 观测，不允许放行。

---

## 4. 后端能力矩阵

**本次拷问最重要的产物**：原方案"静态解析降级为提示"在 `EXEC_SANDBOX=none` 下会**直接移除唯一防线**。

| 后端 | 内核写域约束 | 可 per-call 收敛 | 静态解析角色 | `$()` / heredoc | deny 形态 | 回执要求 |
|---|---|---|---|---|---|---|
| `sandbox-exec` | 有（仅写） | **可**（F6 已有通道） | 纵深一层（软） | 放行，记录 | **不内核化**，静态 hard | 写明"仅写域约束/未隔离网络" |
| `bwrap` | 有 | **需实现**（F10 无参数） | 纵深一层（软） | 放行，记录 | 同上 | 写明"未隔离网络" |
| `docker` | 有（含断网） | **需实现**（F10 无参数） | 纵深一层（软） | 放行，记录 | 同上 | 写明"daemon 权限仍是绕过面" |
| `none` | **无** | 不适用 | **唯一防线（hard，现状不变）** | **拒绝（现状不变）** | 不适用 | 不得出现"已隔离"措辞 |

**判定规则**：`sandbox_argv` 返回 `argv is None`（落到 none）→ `check_command_scope` 必须 hard；返回非 None 且 scope 形态可编译 → 才允许 soft。**由返回值驱动，不由配置推断**，避免"配置说开了但实际落到 none"的错配。

**大小写行**：darwin `_cmp` casefold（F27），Linux 敏感 → 同一 scope 两端可写面不同。矩阵中 `bwrap`/`docker` 行须实测并标注差异，不得默认等价。

**验收标准**
- [ ] 4 种后端 × `$()` / heredoc 用例，行为符合上表
  - heredoc 口径（D2 起）：不再是「一律拒」，而是「正文剥离为 stdin 数据 + 重定向目标判定」；先删续行再切逻辑行、分隔符按 bash 词级引号移除读取、跨行引号/算术深度维护状态、空分组拒、`$`/`~`/反引号等展开形态直接拒、`(( … ))` 内 `<<` 与 `<<<` 整条拒，**读不出即拒**；`$()` 仍拒
- [ ] `EXEC_SANDBOX=none` 时 `$()` 仍被拒（回归用例）
- [ ] `auto` 落到 none 且非 strict 时，静态解析仍为 hard
- [ ] deny 形态在 4 种后端下均不内核化，且回执标注

---

## 5. 关键约束与风险

### 5.1 授权面 vs 声明面（R2 核心）

`scope_allows` 与 `sandbox_allows` 是两套判定，必须证明**前者为真时后者为真**（不放行回退），并**枚举后者为真而前者为假**的放大集合。这是安全证明义务，不是优化项。

### 5.2 截断语义混淆（R5）

`trimmed` 条目命中的是"短前缀"，若调用方以为命中完整 prompt，会**少算 token**。必须在回执与统计两处分列。

### 5.3 成本定价反向风险（R4）

若 `β` 过大，长条目被过度保留，短条目频繁驱逐，可能**增加**短条目重算量。判据用 shadow 期间的**重算 token 总量**，而非命中率。

### 5.4 不得越界宣传

sandbox-exec 下：**网络未隔离、读未限制**（F12），进程可读 `~/.ssh`、`.env`。本改造只涉及写域，不得在文档、回执、日志中暗示"沙箱已隔离"。

### 5.5 deny 模式的失败方向（本修订新增）

`mode=deny` 的 `paths` 是**排除集**，语义为"工作区几乎全开，仅排除若干"。

- 若排除项在内核层失效，结果是**全开**，且命令正常成功、无任何报错。
- 这与 allow 模式的放大（多给权限）性质不同：deny 的放大是**安全回退且静默**。

因此 §3 只给 `shadow`，§4 明确 deny 不内核化。此约束不得因"实现更完整"而放宽。

### 5.6 跨平台大小写差异

`_cmp` 仅在 darwin casefold（F27）。同一 scope 在 Linux 上可写面**更小**（大小写敏感导致 `SRC/` 不匹配 `src/**`）。内核化后 Sandbox 在 APFS 上同样不敏感，但在 Linux 上是大小写敏感的 bind mount —— 两端需分别用例，文档不得声称"语义一致"。

---

## 6. 分阶段实施

| 阶段 | 内容 | 依赖 | 交付物 | 预估 |
|---|---|---|---|---|
| S0 | 记录 commit 基线；消除 U1/U6 | 无 | 基线记录 | 0.5h |
| S1 | R3 canary + R1 停止规则写入 | U4 | `tests/test_position_consistency_canary.py`；规则文档 | 半天 |
| S2 | R2 `shadow` 模式（只算不放行） | S0 | `scope_to_writable_roots` + 回执字段 | 1 天 |
| S3 | R2 `on`（仅 allow 且无 deny，sandbox-exec 优先） | S2、U7/U8 | argv 改造 + C1 形态用例 | 2 天 |
| S4 | R2 bwrap / docker 路径 | S3 | 后端补齐 + 大小写用例 | 2 天 |
| S5 | R4 `shadow` 定价 | S0 | 对照表输出 | 1 天 |
| S6 | R5 `prefix` 降级 | U2 | `oversized` 分支改造 | 1 天 |
| S7 | R4 `on` / R6 归口 | S5 shadow 数据 | 决策记录 | 0.5 天 |

**顺序理由**：S1 先做，因它是唯一"静默错结果"面且成本最低；S2 先 shadow，因授权放大是安全风险，须先观测再放行。

---

## 7. 停止规则（可客观判定）

**规则 A（write-scope 换向）**
> 若第 26 或第 27 轮修复仍在**新增命令族**（diff 出现新的 `_check_<cmd>` 分支或新命令名常量），判定"静态建模"方向错误，停止新增命令族，转 R2。

**规则 B（成本定价失效）**
> 若 shadow 期间成本建议 victim 与现有 victim 的**重算 token 总量**差异 <5%，判定成本维度无收益，R4 判 `not_applicable` 并归档。

**规则 C（截断不可行）**
> 若 U2 结论为两后端均不支持 token 级捕获，R5 整条撤回，改为在文档声明"预算必须 ≥ 最大单条目"（现状已识别的限制）。

**规则 D（canary 不可判定，可判定条件版）**
> 若 U4 实测满足 `δ_reuse < 3 × δ_noise`（即"同路径重复运行抖动与复用路径偏差同量级"），canary 无法区分对错，改用多 seed 采样一致性判据，**不得降低阈值凑通过**。**判据替换 ≠ R3 撤回**（对比规则 C 是整条撤回）：R3 需求与验收条目继续有效，仅"数值阈值判据"被"一致性判据"替换。

- **指标定义（P95 口径）**：
  - `δ_noise`：同一 prompt、同一路径（`full_prefill`）重复运行，各位置点 `k` 的 `logits[k]` 最大绝对差，取 P95；
  - `δ_reuse`：同一 prompt 下 `prefix_reuse(k)` 与 `full_prefill` 在各位置点 `k` 的 `logits[k]` 最大绝对差，取 P95；`k` 集合与 R3 验收一致（`{0, 1, n-2, n-1}`），不可表达的点标 `skip` 且不入统计。
- **触发条件（新增，非实测结论）**：`δ_reuse < 3 × δ_noise`——倍数 `3` 为本登记**新增的设计值，非 U4 实测结论**，U4 实施时复核并回填依据。
- **替换后判据（可判定）**：5 个 prompt × 4 个位置点 `k`（合计 ≥20 组采样），断言 **top-1 token 一致率 100%**（沿用 R3 验收既有"top-1 token 一致"口径，仅把判据从数值阈值换成一致性）。

**规则 E（授权放大失控，可判定条件版）**
> 若 C1 采样中"放大"路径占比 >20%（阈值 20% 为 v2 **原文已有**，见附录 C），或出现任一条"声明允许但内核拒绝"（功能回退），则 R2 判定不可行，回退到"静态解析 + 事后审计"方案，不继续推进内核化。

- **分子（放大口径，与 R2 验收第 2 条同口径）**：`sandbox_allows(p) ∧ ¬scope_allows(p)`——内核放行而声明拒绝的采样路径。
- **分母**：已编译形态（C1 表中判"可编译（等价）"或"可编译但略放大 / 放大须登记"的 pattern）的采样集，每形态 ≥20 条（与 R2 验收第 1 条同口径）；**不可编译 → fail-closed 的形态不入分母**（不产生内核放行面）。
- **可判定触发**：`分子数 ÷ 分母数 > 20%`，或 R2 验收第 1 条的正向断言出现任一失败样本（`scope_allows==True` 但 `sandbox_allows==False`，即功能回退）。
- **动作（可判定、有序）**：
  1. `EXEC_SANDBOX_WRITE_SCOPE` 由 `on` 置 `off`；
  2. 实施退回 S2（`shadow`：只算不放行，保留观测）；
  3. R2 判 `not_feasible`，并登记触发本规则的采样数据（分子/分母明细）；
  4. 再推进前置条件（须全部满足）：形态改写（scope 声明侧）或缺陷修复（实现侧）→ 按本口径重采样通过（占比 ≤20% 且零功能回退）→ 用户显式确认。

---

## 8. 拷问记录（盲点 → 方案修订）

| # | 拷问暴露的盲点 | 对原方案的影响 | 修订 |
|---|---|---|---|
| B1 | `plan_trim` 已存在（F15） | 原"新增按 token 截断"是**重复造轮子** | R5 改为只改 `oversized` 分支 |
| B2 | `is_generation_safe_hybrid_checkpoint` 已存在（F20） | 原"hybrid 不可截断需处理"部分已实现 | R3 缺口精化为"数值等价"，非"hybrid 处理" |
| B3 | sandbox-exec 已做写域约束且可写根是常量（F7/F9） | 原"从零建 OS 级隔离"夸大工作量 | R2 精确为"常量 → per-call 参数" |
| B4 | glob vs subpath 语义差（F3/F8） | 原方案会导致**授权放大** | 新增 C1 + 可编译形态表 + 双向断言 |
| B5 | `none` 后端无内核层（F13） | 原"静态解析降级为提示"在 none 下**移除唯一防线** | 新增 §4 矩阵，由 `argv is None` 驱动 |
| B6 | 沙箱不隔离网络/读（F12） | 原表述可能被读作"沙箱加固" | 新增 §5.4 禁止越界宣传 |
| B7 | `_next_victim` 不读 nbytes（F16） | 原"LRU 对长度无感"表述不准 | 精化为"角色排名 + 桶内 FIFO"，机制在 `_ordered_keys` |
| **B8** | **`WriteScope` 有 deny 模式，`paths` 是排除集（F25）** | **原方案把 scope 当作纯 allow 白名单，deny 会被误编译为放行** | **新增 C2 + §5.5 + §3 只给 shadow + §4 不内核化** |
| **B9** | **`deny_paths` 优先于 allow（F26）** | **allow 白名单丢失 deny 优先级，子 scope 的 deny 约束被抹掉** | **C2 处置第 2 条：含 `deny_paths` 即降级为不内核化** |
| **B10** | **`_cmp` 跨平台大小写不同（F27）** | **原方案默认"语义一致"** | **新增 §5.6 + 矩阵大小写行 + 两端分别用例** |

---

## 9. 未决问题与决策登记（需人工决策，不由实施方自定）

| # | 问题 | 选项 | 影响 |
|---|---|---|---|
| Q1 | 授权放大是否可接受 | (a) 零放大，不可编译即拒（表达力损失）(b) 允许放大并逐条登记 | 决定 R2 表达力与安全权衡 |
| Q2 | `none` 后端是否允许 soft | (a) 永远 hard（推荐）(b) 由用户显式承担 | 决定默认安全姿态 |
| Q3 | R5 截断是否改变"命中率"定义 | (a) 分列 full/trimmed (b) 合并 | 影响历史 A/B 可比性 |
| **Q4** | **deny 形态是否永久排除在内核化之外** | (a) 永久排除（推荐）(b) 待 SBPL deny 语义验证（U8）后再议 | 决定 §3/§4 是否可放宽 |
| **Q5** | **文件级 scope（`X/Y.py`）是否依赖 U7** | (a) 等 U7 结论 (b) 一律按"目录前缀"处理 | 决定是否支持精确文件授权 |

### 9.1 决策登记（当前取值 / 状态）

> 登记口径：**"默认假设"是假设，不是决定**。凡标"待用户决策 / 待定"的条目，在用户确认前不得作为既定事实引用；标"已定"的条目为前文（§4 / R5 等）已固化的事实，本表仅登记，不新增授权。

| # | 问题 | 当前取值 / 状态 | 状态分类 | 依据（锚点） | 影响 |
|---|---|---|---|---|---|
| Q1 | 授权放大是否可接受 | 默认假设 **(b) 允许放大并逐条登记**。**这是假设，非决定**：`EXEC_SANDBOX_WRITE_SCOPE=on` 启用前必须经用户确认 Q1 | 待用户决策 | C1 表（`X` 行"可编译但略放大…须登记"、`X/**/Y` 行"放大，须登记"）；R2 验收第 2 条（逐条登记 + 显式处置）；§5.1（枚举放大集合为证明义务）；规则 E（20% 上限预设"放大受控可接受"） | R2 |
| Q2 | `none` 后端是否允许 soft | **已定 (a) 永远 hard**（前文已固化，本表登记既成事实） | 已定 | §4 矩阵 `none` 行（"唯一防线（hard，现状不变）"）；§4 判定规则（`argv is None` ⇒ 必须 hard）；§4 验收（"`EXEC_SANDBOX=none` 时 `$()` 仍被拒"） | R2 |
| Q3 | R5 截断是否改变"命中率"定义 | **已定 (a) 分列 full / trimmed** | 已定 | R5 验收第 5 条（"命中统计区分 `full` / `trimmed`，复用率不得混算"）；§5.2（回执与统计两处分列） | R5 |
| Q4 | deny 形态是否永久排除在内核化之外 | 默认假设 **(a) 永久不纳入内核化**。**这是假设，非决定**：若用户选 (b)（待 U8 后再议），须先按 C-4 撤销 §5.5 末句禁令并同步修订前文五处，再议方生效 | 待用户决策 | §5.5（deny 失败方向 = 静默安全回退；"此约束不得因'实现更完整'而放宽"）；C2 处置第 3 条；§3（`EXEC_SANDBOX_WRITE_SCOPE_DENY` 不提供 `on` 及理由）；§4 矩阵 deny 形态列；附录 B | R2 |
| Q5 | 文件级 scope（`X/Y.py`）是否依赖 U7 | **待定（阻塞于 U7）**，默认假设 (a) 等 U7 结论。U7 未决期间，文件级 pattern 按 C1 表 `X`（无通配）行处理：编译为字面前缀、登记"略放大" | 待定（依赖 U7） | §1.2 U7 行（"决定文件级 scope 能否直译"）；C1 表 `X` 行；§6 S3（依赖 U7/U8） | R2 |
| D6 | deny 裸目录名（如 `src`）应扩展为子树语义，还是拒绝声明 | **已定：扩展为 `p + "/**"`（只收紧）**。此前为未登记缺陷：`deny ["src"]` 解析成功但只匹配 rel 恰为 `src`，而写目标永远是文件，故实测对 `src/…/sandbox.py` 返回 `(True, "")`——声明禁止却全量放行且无告警 | 已定（D1 修复） | 拒绝方案会误伤 `deny ["a.txt"]` 这类精确文件条目（无法从字符串区分文件/目录）；`X/**` 对文件目标命中集不变、对目录目标收紧为子树，方向恒安全。回归 `test_deny_bare_directory_name_excludes_whole_subtree` 等 9 例（含 allow 零回归） | R2 |

### 9.2 冲突记录（前文预设 vs 待决状态）

| # | 冲突 | 说明 | 处置 |
|---|---|---|---|
| C-1 | Q1 标"待用户决策"，但前文已按选项 (b) 预设 | C1 表（`X` 行、`X/**/Y` 行"须登记"）、R2 验收第 2 条（放大逐条登记 + 显式处置）、§5.1（枚举放大集合）、规则 E（20% 阈值预设放大可接受）四处均按 (b) 语义书写 | 维持现状书写；§9.1 已显式标注 Q1 为假设。若用户选 (a)，须同步修订 C1 表、R2 验收第 2 条、§5.1、规则 E 四处 |
| C-2 | Q2 列于 §9"未决"，但 §4 已按 (a) 固化 | §4 矩阵 `none` 行、判定规则（`argv is None` ⇒ hard）、回归验收均为 hard；选 (b) 则 §4 需整表重写 | §9.1 登记为"已定 (a)"；后续修订应将 Q2 移出未决清单 |
| C-3 | Q3 列于 §9"未决"，但 R5 与 §5.2 已按 (a) 分列书写（与 C-2 同型） | R5 验收第 5 条"区分 `full` / `trimmed`，复用率不得混算"；§5.2"回执与统计两处分列"——两处均为 (a) 语义，选 (b) 合并将直接违反该验收 | §9.1 登记为"已定 (a)"；选 (b) 须先修订 R5 验收与 §5.2 |
| C-4 | Q4 选项 (b) 为"待 U8 验证后再议"留余地，但前文至少五处已按 (a) 永久排除书写 | C2 处置第 3 条（`mode=deny` 默认不纳入内核化）、§3（`WRITE_SCOPE_DENY` 不提供 `on` 及理由）、§5.5（"此约束不得因'实现更完整'而放宽"）、§4 矩阵（deny 形态三行均"不内核化"）、附录 B（"本方案选择不解决"）；R2 验收第 4 条与 §4 验收亦含 deny 断言 | 维持 (a) 为默认假设并标注须用户确认；若用户选 (b)，须先撤销 §5.5 末句禁令，再同步修订其余各处，否则 (b) 无效 |

---

## 10. 验收清单（逐项可勾）

**R1**
- [ ] 停止规则已写入仓库文档且可被提交历史判定

**R2**
- [ ] `EXEC_SANDBOX_WRITE_SCOPE=off` 下与改造前行为逐字节一致
- [ ] C1 形态表逐行有用例（`X/**` 等价、`X/**/Y` 放大、`X*`/`**/Y` 不可编译）
- [ ] 双向采样断言通过，放大集合逐条登记，占比已计算（规则 E 判据）
- [ ] 含 `deny_paths` 与 `mode=deny` 的 scope 不被内核化，回执标注
- [ ] 四种后端行为符合 §4 矩阵
- [ ] `none` 后端 `$()` 仍被拒绝（回归）
- [ ] 回执 note 如实描述实际能力（无"已隔离"越界措辞）
- [ ] 大小写差异在 bwrap/docker 行实测并记录

**R3**
- [ ] canary <60s 跑完，阈值有实测依据
- [ ] 失败信息含位置点与偏差量
- [ ] 不可表达的位置点标 `skip` 而非伪造通过

**R4**
- [ ] shadow 对照表产出，规则 B 判据已计算
- [ ] 成本相同时回退到 rank+FIFO（确定性单测）

**R5**
- [ ] `reject` 默认行为不变
- [ ] `prefix` 下 trimmed 标记贯穿统计与回执
- [ ] 截断 key 通过 `matched_prefix_key` 校验，且不与完整条目并存

**R6**
- [ ] 两套语义策略已归口且标注清晰

**全局**
- [ ] 无新增未登记的后端能力宣称

---

## 附录 A：涉及文件清单

**llm-first-loop**
- `src/llm_loop/core/write_scope.py`：新增 `scope_to_writable_roots()`（C1/C2 实现），需读取 `mode` / `deny_paths`
- `src/llm_loop/core/command_scope_guard.py`：`check_command_scope` 增 hard/soft 模式参数
- `src/llm_loop/tools/sandbox.py`：`sandbox_argv` 增 `writable_roots`；`bwrap_argv` / `docker_argv` 增路径集合
- `src/llm_loop/tools/builtin/execute_command.py:803`：透传 scope 根；回执增字段（含"未内核化"标注）
- `docs/EXECUTION-ISOLATION.md`：更新边界描述（per-call 语义、deny 不纳入、大小写差异）
- `tests/`：C1 形态用例、deny 用例、4 后端矩阵用例、零回归用例

**StateBraid**
- `src/statebraid/cache/policy.py`：`plan_admission` oversized 分支；`_next_victim` 成本维度（shadow）
- `tests/test_backend_conformance_contract.py`：数值等价用例
- `tests/test_position_consistency_canary.py`（新增）
- `README.md`：如 R6 选 (b)，补组合限制声明

## 附录 B：本方案不解决的问题

- shell 内脚本内容对静态解析不可见（内核化后由沙箱兜底，但**无法告知用户"这条命令想写哪"**）
- 网络出站与读取面（不在写域范围）
- docker daemon 自身权限
- sandbox-exec 长期可用性（macOS 私有接口）
- deny 形态的内核表达（本方案选择不解决，而非未想到）

## 附录 C：文档修订史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-10-31 | 初稿：R1-R6、设置项、矩阵、停止规则 |
| v2 | 2026-10-31 | 补 F25-F29；新增 C2（deny 语义）、§5.5、§5.6、B8-B10、Q4-Q5、规则 E；R2 按 scope 形态分化处置 |
| v3 | 2026-10-31 | 新增 §9.1 决策登记（Q1-Q5 当前取值/状态，待决项显式标注"假设非决定"）与 §9.2 冲突记录（C-1..C-4）；规则 D/E 补可判定指标（δ_noise/δ_reuse、分子/分母口径）与回退动作 |
| v4 | 2026-10-31 | 补 F25b 与 §9.1 D6：D1 返修——deny 非 `/**` 结尾条目在解析层补目录语义（`_expand_deny_pattern`）。修前 `deny ["src"]` 解析成功却全量放行（实测 `(True, "")`），修后拒绝子树；`X/**` 对文件目标命中集不变，allow 模式零影响 |
