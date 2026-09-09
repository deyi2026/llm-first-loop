# 缓存门禁·前缀表面契约收缩方案（R1–R4）

- 版本: v1
- 日期: 2026-09-10
- 状态: 已实施（f938428，v2 前缀面契约）；本文档为该实现的设计依据
- 范围: `cache_health.py` 发送前门禁（preflight/postcheck）的契约维度收缩与指纹语义对齐
- 前置拷问: 五问（per-model 契约数据源、骨架分层生产调用方、动态注入撤离、tools_fp 归类、双门闸语义）

---

## 0. 结论先行

把"前缀表面"从**一个混判指纹**收缩为**两个正交指纹**，分别裁决：

```
system_fp = stable_digest(system_prompt)   # 消息前缀：必须跨轮字节稳定
tools_fp  = stable_digest(tools)           # 工具表面：每轮可合法变化
```

- `system_fp` 漂移 → 真漂移（bug/部署/非法 prompt 文本写入）→ `force_head_keep` + `_gate_drift_count`。
- `tools_fp` 变化 → 不是漂移；缓存边界失效（已由 `_cache_boundary_protection` 的 combined `stable_fp` 正确处理），门禁只做审计，不干预。

同时：**删除死代码分层**（H3' 骨架分层 + `(session, model)` 桶契约），把 preflight/postcheck 从"4 参 + 两层分桶"简化为"3 参 + 两组基线"。不补 model 维度、不接分层——因为前缀已自我简化为编译期常量。

---

## 1. 现状与已证实事实

以下均经源码逐行核实（本轮会话证据）：

| # | 事实 | 证据 |
|---|------|------|
| F1 | `build_system_prompt(extra="")` 无 model 参数，返回 `_BASE_PROMPT` 常量 | `prompt.py:12` |
| F2 | `run_base_assembly` 计算 `_base_fp = stable_digest([...base[:prefix_len]... + [system_prompt]])`，再与 `tool_prefix_fp` 折成 combined `stable_fp` | `base_assembly.py:58-70` |
| F3 | `preflight(session_id, result.stable_fp)` 只传 2 参，`skeleton_fp` 缺省 | `base_assembly.py:71` |
| F4 | `postcheck(sess.session_id, cache_gate_stable_fp)` 只传 2 参，`skeleton_fp`/`model_ref` 均缺省 | `tail_assembly.py:156` |
| F5 | interop 注入是空操作：`_inject_interop_messages` 原样返回，`prefix_len` 恒 0 | `interop.py:216-229`、`base_assembly.py:52-54` |
| F6 | switch notice 08-27 已删，只 `record_action`（R8.8：切换不写 prompt 文本） | `interop.py:235-250`、`cache_health.py:966-967` |
| F7 | memory 检索 08-18 已移到尾部 GATE_NOTE，不进前缀 | `ingress_resolution.py:215-218` |
| F8 | `cache_gate_tools_fp = stable_digest(tools)` 每轮由 tool cycle 投影产生 | `engine.py:1539`、`runstate.py:61` |
| F9 | `tool_prefix_fp` 已传入 `run_base_assembly`，但 tail_assembly 未收 tools_fp | `build.py:467` vs `build.py:570` |
| F10 | 缓存边界保护用 combined `stable_fp`（含 tools_fp），tools 变 → 边界失效（返回 0 不保护） | `build.py:90-91`、`build.py:68-99` |
| F11 | `projection_gate` 的 `system_fp = stable_digest(system_prompt)`（裸字符串），且 `memory_fp`/`interop_fp` 硬编码 `stable_digest([])` | `projection_gate.py:60-68` |
| F12 | `stable_digest` 对 list 与裸字符串产出**不同**哈希（list → JSON 数组，str → 原样） | `history.py:1746-1756` |
| F13 | `_skel_baselines`/`_controlled_change_count`（H3' 骨架分层）与 `_model_prefix_contract`/`_contract_drift_count`（桶契约）已初始化 | `cache_health.py:210-227` |
| F14 | `skeleton_fp`/`model_ref` 参数除 cache_health.py 自身外**无任何生产调用方喂值**（全库搜索仅命中定义/内部） | search_files 结论 |

---

## 2. 问题定义（五个拷问的收敛结论）

1. **per-model 契约无数据源**：`build_system_prompt` 无 model 参（F1），R8.8 已定"切换不写 prompt 文本"（F6）。`(session, model)` 分桶是对一个全局单值做 N 份复制，不携带信息。
2. **骨架/稳定性分层是死代码**：`skeleton_fp` 无生产调用方（F14），`preflight`/`postcheck` 均 2 参调用（F3/F4），H3' 三层裁决从未被喂到 skeleton 输入。
3. **动态注入已全部撤离前缀**：interop 空操作（F5）、switch notice 已删（F6）、memory 移到尾部（F7）。`base[:prefix_len] == []`，`_base_fp` 退化为 `stable_digest([system_prompt])`。
4. **tools_fp 是"受控变更"还是"漂移"分类错误**：tools 变使缓存边界失效（F10），但当前 preflight 用 combined `stable_fp` 判漂移 → tools 变被误判为"锚点漂移"并触发 `force_head_keep`——而 `force_head_keep` 压历史头**救不了 tools 导致的缓存失效**。
5. **双门闸对同一常量的语义不一致 + 哈希源不一致**：
   - `cache_health` 把 system 折进 combined `stable_fp` 当"漂移"管；`projection_gate` 把 system 当"版本变化（合法）"管。
   - 更硬的是 F12：`base_assembly` 的 `_base_fp = stable_digest([system_prompt])`（列表）≠ `projection_gate` 的 `system_fp = stable_digest(system_prompt)`（裸字符串）。同一 system 文本两处产出不同指纹。

---

## 3. 设计决策

### R1（核心）：前缀表面拆成两个正交指纹，分开裁决

- 新增 canonical `system_fp = stable_digest(system_prompt)`（**裸字符串**，对齐 projection_gate）。
- 保留现有 combined `stable_fp = stable_digest({"base_fp": _base_fp, "tools_fp": tool_prefix_fp})` 的**计算不变**——它继续服务 `_cache_boundary_protection`（F10）与 `cache_prefix_epoch` 的水位比较，不参与漂移分类。
- 门禁的漂移判定改为 key 在 `system_fp` 上：
  - `system_fp` 变 → 真漂移：`force_head_keep = True` + `_gate_drift_count += 1` + `gate_note_pending = True`。
  - `tools_fp` 变 → 仅审计：`_tools_change_count += 1` + `logger.info`，**不干预**（缓存边界失效已由 F10 的 combined 比较处理）。

**为什么 tools 不干预**：tools 数组变化使 provider 缓存前缀整体失效，压历史头无意义；正确动作是让边界自然失效 + 观察。门禁对 tools 的职责是"可见性"，不是"纠正"。

### R2：契约按"部署常量"存，不按 (session, model) 存

- 删除 `_model_prefix_contract`（`(session → model → 骨架指纹)`）与 `_contract_drift_count`。
- `system_fp` 基线仍 per-session 存（`_system_baselines`），因为不同会话 session_id 不同，且基线是"该 session 的锚点"语义；但**不再引入 model 维度**。
- 未来若推翻 R8.8、`build_system_prompt` 按 model 参数化，才引入 model 维度——**且那时必须同时撤销"切换不应改变骨架"这条不变式**（per-model prompt 必然骨架不同）。

### R3：删除死代码分层，preflight/postcheck 简化为 3 参

- 删除 `_skel_baselines`、`_controlled_change_count`、`skeleton_fp` 参数、`model_ref` 参数、H3' 三层分支（`skeleton_fp == prev_skel → 受控变更` 分支）。
- 新签名：

```python
def preflight(self, session_id: str, system_fp: str, tools_fp: str) -> None: ...
def postcheck(self, session_id: str, system_fp: str, tools_fp: str) -> str | None: ...
```

- 保留 `_gate_drift_count`（告警出口）不变。

### R4：system_fp 与 projection_gate 同源对齐

- 门禁的 `system_fp` 采用**裸字符串** `stable_digest(system_prompt)`，与 `projection_gate.py:66` 完全同形（消除 F12 哈希源不一致）。
- 语义对齐规则（两门闸对同一常量给同一判定）：
  - system 文本变 → `projection_gate` 视为版本变化（合法，进 ver 使缓存行过期）；`cache_health` 视为 **system 漂移**（审计 + 干预）。
  - tools 数组变 → `projection_gate` 不感知（它不含 tools 指纹）；`cache_health` 视为**工具表面变化**（仅审计，不干预）。
  - **只有"system 在无版本变化时字节漂移"才算 cache_health 的 drift**——而"system 文本合法升级"应通过版本/baseline 一次性重建基线消化，不应每轮报漂移。

**注意**：system 文本升级与 system 字节漂移在指纹上不可区分，两者都表现为 `system_fp != 基线`。故 R4 的判定退化为：`system_fp` 变化一律按 drift 处理（保守、fail-open），但**只在真正发生文本写入的罕见时刻触发**；正常稳态下 `system_prompt` 是常量，此路径零开销。这一保守语义与现状一致，仅把 tools 变化从中剔除。

---

## 4. 数据流（before / after）

### before（当前）

```
engine.py:1539  cache_gate_tools_fp = stable_digest(tools)
                        │
build.py:467 ──────────┤ tool_prefix_fp
base_assembly.py       │
  _base_fp = stable_digest([system_prompt])     (前缀已空)
  stable_fp = digest({base_fp, tools_fp})       (混判)
  preflight(session_id, stable_fp)              ← system 漂移与 tools 变化混在一起
build.py:472  cache_gate_stable_fp = stable_fp
build.py:570  tail_assembly(cache_gate_stable_fp=stable_fp)
tail_assembly.py:156  postcheck(session_id, stable_fp)
```

### after（目标）

```
base_assembly.py
  system_fp = stable_digest(system_prompt)          # canonical（裸字符串）
  _base_fp  = stable_digest([system_prompt])        # 保留，供 combined
  stable_fp = digest({base_fp, tools_fp})           # 保留，供边界保护/epoch
  preflight(session_id, system_fp, tool_prefix_fp)  # 拆开裁决
build.py
  cache_gate_system_fp = system_fp
  cache_gate_stable_fp = stable_fp                  # 仍供 _cache_boundary_protection
  tail_assembly(cache_gate_system_fp, cache_gate_tools_fp)
tail_assembly.py
  postcheck(session_id, system_fp, tools_fp)
```

---

## 5. 改动点清单（精确到文件/函数/行）

### 5.1 `src/llm_loop/core/cache_health.py`

| 位置 | 改动 |
|------|------|
| `__init__` 208-227 | 删除 `_skel_baselines`、`_controlled_change_count`、`_model_prefix_contract`、`_contract_drift_count`；`_baselines` 改名 `_system_baselines`（语义明确）；新增 `_tools_baselines: dict[str, str]`、`_tools_change_count: int`。保留 `_gate_drift_count`。 |
| `preflight` 925-950 | 签名改 `(session_id, system_fp, tools_fp)`；删除 `skeleton_fp` 分支；`system_fp != 基线 → force_head_keep + gate_drift_count + gate_note_pending`；`tools_fp != 基线 → 仅 logger.info + _tools_change_count`；首次建立两组基线。 |
| `postcheck` 952-1012 | 签名改 `(session_id, system_fp, tools_fp)`；删除 skeleton/model 契约块（977-992）；`system_fp` 变化 → 漂移提示 + 计数；`tools_fp` 变化 → 仅审计；总是更新两组基线。 |

### 5.2 `src/llm_loop/core/prompt_build/stages/base_assembly.py`

| 位置 | 改动 |
|------|------|
| `BaseAssemblyResult` 26-32 | 新增字段 `system_fp: str = ""`。 |
| `run_base_assembly` 58-71 | 新增 `_system_fp = stable_digest(system_prompt)`（裸字符串）；`result.system_fp = _system_fp`；`_base_fp` 与 `stable_fp` 计算**原样保留**；`preflight(session_id, _system_fp, tool_prefix_fp)`。 |

### 5.3 `src/llm_loop/core/loop/build.py`

| 位置 | 改动 |
|------|------|
| 471-472 | 新增 `_state.cache_gate_system_fp = _asm.system_fp`（与 `cache_gate_stable_fp` 并列回写）。 |
| 570 | tail_assembly 调用新增 `cache_gate_system_fp` 与 `cache_gate_tools_fp` 实参。 |

### 5.4 `src/llm_loop/core/prompt_build/stages/tail_assembly.py`

| 位置 | 改动 |
|------|------|
| `run_tail_assembly` 签名 | 新增 `cache_gate_system_fp: str = ""`、`cache_gate_tools_fp: str = ""`。 |
| 156 | `postcheck(sess.session_id, cache_gate_system_fp, cache_gate_tools_fp)`。 |

### 5.5 `src/llm_loop/core/loop/runstate.py`

| 位置 | 改动 |
|------|------|
| 56-61 | 新增 `cache_gate_system_fp: str = ""`（紧邻 `cache_gate_stable_fp`）。 |

---

## 6. 删除面（死代码）

以下符号**删除**（生产无 producer + 无外部消费路径，删除不改变行为）：

| 符号 | 位置 |
|------|------|
| `_skel_baselines` | `cache_health.py:216` |
| `_controlled_change_count` | `cache_health.py:217` |
| `_model_prefix_contract` | `cache_health.py:226` |
| `_contract_drift_count` | `cache_health.py:227` |
| `preflight` 的 `skeleton_fp` 参数 + 受控变更分支 | `cache_health.py:925-950` |
| `postcheck` 的 `skeleton_fp`/`model_ref` 参数 + 骨架/契约分支 | `cache_health.py:952-1012` |

**保留**：`_gate_drift_count`（告警出口）、`_baselines`（改名 `_system_baselines` 继续用）、combined `stable_fp` 的边界保护路径。

---

## 7. 不变式（设计必须维持）

1. **fail-open**：preflight/postcheck 任何异常都不阻断发送（现有 try/except 语义保留）。
2. **system 常量稳态零开销**：正常会话中 `system_prompt` 每轮不变，`system_fp` 基线比较为恒定相等，drift 路径不触发。
3. **tools 变不干预**：tools 数组变化只审计，绝不触发 `force_head_keep`。
4. **缓存边界仍对 tools 敏感**：combined `stable_fp` 计算不动，`_cache_boundary_protection` 对 tools 变化的失效判定继续生效。
5. **两门闸 system 指纹同形**：cache_health 与 projection_gate 均用 `stable_digest(system_prompt)`（裸字符串），消除 F12 源不一致。
6. **删除不改行为**：被删的 `_skel_baselines`/`_model_prefix_contract` 无生产调用方，删除前后对外可见行为一致。

---

## 8. 风险与回滚

**风险**：

- R1 把 tools 从 drift 中剔除后，若某些 provider 的缓存命中率确实对"工具集变化但 system 未变"有隐性依赖，可能观察到命中率统计口径变化——但这是**统计可见性**变化，不是正确性回归；边界保护（F10）已保证缓存前缀不跨工具集复用。
- R2 删除 model 维度后，若未来引入 per-model prompt，需要重新设计（文档已明确触发条件）。

**回滚**：单 commit 可逆；`git revert` 恢复 combined `stable_fp` 判漂移的旧语义。删除的死代码可由 git 历史恢复，无数据迁移。

---

## 9. 验收标准

1. `preflight`/`postcheck` 签名变为 `(session_id, system_fp, tools_fp)`，全库无 `skeleton_fp`/`model_ref` 传参残留。
2. `system_fp` 变化 → `_gate_drift_count` 自增 + 告警出口可观测；`tools_fp` 变化 → `_tools_change_count` 自增，无 `force_head_keep`。
3. `stable_digest(system_prompt)`（裸字符串）在 cache_health 与 projection_gate 产出相同值（单测断言）。
4. 现有 `_cache_boundary_protection` 对 tools 变化的失效判定不回归（combined `stable_fp` 不变）。
5. 删除的 6 个符号全库无引用（`grep` 验证）。
6. 正常会话稳态下无 drift 误报（`system_prompt` 常量）。

---

## 10. 开放问题

- 是否需要把 `system_fp()` 提取为 `history.py` 的共享 helper（取代 base_assembly 与 projection_gate 各自调用 `stable_digest(system_prompt)`）？最小化方案不提取；若要强一致，建议提取并在两处引用。
- `_tools_change_count` 是否需要进 snapshot/审计文件，还是仅 logger？当前方案建议仅 logger + 计数，避免扩大审计面。
