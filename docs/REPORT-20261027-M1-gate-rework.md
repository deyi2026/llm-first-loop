# M1 门禁返工报告（dev 报告 · 门禁返工小节）

- 日期：2026-10-27；分支 feat/desktop-gui-browser-tooling（返工基线 HEAD=04afd9eff）
- 门禁拦截：tier0 `tests/unit/test_arch_guards.py` 的 test_function_lines_ratchet_within_baseline 与 test_global_redline_300（棘轮零增长 + 全局红线）
- 处置原则：**只重构、不改护栏、不动登记**——`tests/guards/function_size_baseline.json` 本次零改动（未运行 regen 脚本；既有 key 登记值零上调、零新增 key）

## 1. 失败事实与回落结果（AST 口径：end_lineno - lineno + 1）

| 函数 | 节/登记值 | 返工前实测 | 重构后 | 结论 |
| --- | --- | --- | --- | --- |
| src/llm_loop/browser/action.py::execute | legacy 393 | 430 | 387 | 回落 ≤393 |
| src/llm_loop/tools/builtin/browser_perceive.py::execute | legacy 371 | 392 | 344 | 回落 ≤371 |
| browser_semantic_operation.py::_compile_short_steps | fl 204 | 244 | 202 | 回落 ≤204 |
| browser_semantic_operation.py::execute_request | fl 228 | 242 | 222 | 回落 ≤228 |
| browser_semantic_operation.py::_compact_projection | 未登记（≥120 需登记） | 126 | 114 | 回落 <120，无需登记 |

注：父代理委派清单列了 4 条，实测对账发现第 5 条（execute_request 228→242）同样超登记，一并回落；五条全部仅靠抽 helper 解决，无任何登记变更。

## 2. 抽出的 helper 清单（全部单一职责、实测行数远低于 120 收录门槛，无需登记）

src/llm_loop/browser/action.py
- `_recheck_upload_dispatch_args`（方法，40 行）：fix(P0-1) upload 复验（resolve+同策略再查）+ dispatch_args 组装；失败时产出既有 rejected 回执，execute 原处一行调用后早返回
- `_post_dispatch_observation`（方法，38 行）：dispatch 后 after-观察 + 语义 diff（证据面，失败只降级不拦截），行为逐句等价搬迁
- `_dispatch_safe_arg_facts`（模块级，14 行）：upload 内容摘要只取复验后的解析路径（原 safe_args 展开 kwargs 收拢）

src/llm_loop/tools/builtin/browser_perceive.py
- `_attach_vision_evidence`（方法，38 行）：snapshot 回执的 vision 证据分支整体搬迁（unavailable/failed/payload 边界/ok 全语义保留，captured_at 仍在捕获时刻打点）
- `_vision_meta`（模块级，11 行）：M1 B10 元数据组装（page_id/world_version/captured_at）

src/llm_loop/tools/builtin/browser_semantic_operation.py
- `_navigate_step_clause` / `_upload_step_clause` / `_type_step_clause`（模块级，12/23/20 行）：short-step 编译分支抽出；校验顺序、错误码、target 转换时点逐句保持（upload/type 传 cls 以保持「参数校验先于 target 转换」的错误优先级）
- `_mutate_clause_receipt`（模块级，34 行）：mutate clause 回执构造 + M1 upload/type 机械回声（仅 ack 后回显文件事实；type 只回长度+前 20 字符）
- `_lift_m1_compact_echoes`（模块级，18 行）：compact 回执 M1 回声提升与 halt 拒绝码透出（pre-M1 回执逐字节不变）

## 3. 复跑结果（全部绿）

- `tests/unit/test_arch_guards.py`：**40 passed**（两条 ratchet 测试全绿；守卫按 staged 口径读源，先 git add 后复验）
- `tests/unit/test_browser_m1_upload_type_vision_v01.py`：26 passed
- `tests/unit -k "browser"`：642 passed, 8760 deselected
- 改动文件对应既有测试（action/perceive/semantic_operation 相关 14 个文件）：128 passed
- 静态诊断棘轮（scripts/check_static_diagnostics.py）：ruff PASS（new=0，touched files clean）；pyright PASS（new=0，changed_file_diagnostics=0）

## 4. 过程纪律记录

- pyright 首轮抓到 1 处新增类型错（_recheck_upload_dispatch_args 原签名不允许首槽 None），已修正：返回类型改为 `tuple[dict | None, dict | None]` 并在 execute 内以不变量断言窄化（不变量恒真，无行为变化）；复跑 pyright new=0
- 未跑全量 ci_gate（按委派约束，仅静态诊断棘轮 + 相关子集）

## 门禁返工 2（fix(gate2)：环境访问层 + 本地时间权威）

- 日期：2026-10-27；返工基线 HEAD=ad3f8f1c2；全量门禁红数对账确认 2 条代码级回归（另 5 条已排除为门禁子集状态污染，单独复跑全绿，不属本次改动）

### 改动点

1. **环境变量直读（test_runtime_env_access_gate，签名棘轮零容忍）**
   - `src/llm_loop/browser/action.py` 的 `upload_allow_roots` / `upload_max_file_bytes` 原直读 `os.environ.get("LFL_BROWSER_UPLOAD_ALLOW_ROOTS" / "LFL_BROWSER_UPLOAD_MAX_FILE_BYTES")`，新增 2 条未登记签名
   - 修法：借道 sanctioned 访问层 `llm_loop.config._raw_env`（与 `tools/mcp_auth.py` 同法——「环境访问点收口，不直读 os.environ」；调用点保持字面量 key 可审计）。`_raw_env` 内部读已在 baseline 登记（`src/llm_loop/config.py|_raw_env|bulk:raw|<all>`=1），跨模块调用零新增签名；语义等价（未设置/空值 → "" → 缺省边界），monkeypatch.setenv 即时生效性不变
   - baseline 白名单与 ratchet 登记零改动、零豁免
2. **UTC 墙钟（test_timekeeping_local：新 LFL-owned 墙钟记录必须用主机本地权威）**
   - `src/llm_loop/tools/builtin/browser_perceive.py` 的 B10 `captured_at` 原为 `datetime.now(UTC).isoformat(timespec="milliseconds")`
   - 修法：改用 `llm_loop.timekeeping.system_local_now()`（仓库既有时间权威，`datetime.now().astimezone()` 主机本地、带偏移）；删除 `from datetime import UTC, datetime`。字段名/格式不变（ISO 8601 毫秒 + 偏移），语义保持「截图时刻、可比较、带偏移」，M1 断言（`startswith("202")`）无需放宽
   - 过程纪律：首轮复跑失败 1 次——修复注释里写了 `datetime.now(UTC)` 字面量，而该测试是纯文本子串扫描；改写注释措辞后全绿

### 复跑结果（全部绿）

- `tests/unit/test_runtime_env_access_gate.py`：**6 passed**（改后签名零新增）
- `tests/unit/test_timekeeping_local.py`：**4 passed**
- `tests/unit/test_browser_m1_upload_type_vision_v01.py`：**26 passed**
- `tests/unit/test_arch_guards.py`：**40 passed**
- 回归面：`tests/unit -k "browser"` 642 passed；`test_config_inline_comment` 6 passed（`_raw_env` 行为无变化）
- ruff/pyright：改动两文件 clean（ruff All checks passed；pyright 0 errors/0 warnings）

### captured_at 格式样例

- 修复前：`2026-10-27T10:55:15.593+00:00`（UTC）
- 修复后：`2026-10-27T18:55:15.593+08:00`（主机本地权威，偏移随宿主时区）

