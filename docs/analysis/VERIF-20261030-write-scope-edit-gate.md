# 核实记录：write_scope 写侧闸是否被 `edit()` 绕过

- 核实时间：2026-10-30 12:54–13:10（Asia/Shanghai）
- 待核断言（来自我自己上一轮的汇报）：「`file_service.py` 文档说 `edit()` 支持 `write_scope`，但实际只接了 `observe()`，`edit()` 仍绕过 scope 闸。」
- 核实方式：HEAD 与工作树**双读**（不据单一时点的印象下结论）+ 两条独立验证来源（并发会话的测试套件 + 我自写的对抗探针）
- 结论：**该缺口在当前工作树已不成立，无需再改代码**；但特性**尚未提交**，且存在三条设计已声明的边界（见「残余风险」）。

## 1. 逐层事实

| 层 | 事实 | 依据 |
|---|---|---|
| HEAD（`48f9dc003`） | `src/llm_loop/workspace/file_service.py` 全文**无** `write_scope` / `scope_allows` ⇒ HEAD 上整个 write_scope 特性不存在 | `git show HEAD:src/llm_loop/workspace/file_service.py \| grep -n "write_scope\|scope_allows"` ⇒ 无命中（exit 1） |
| 工作树（WIP） | `edit()` 与 `observe()` **都**接了闸：`_enforce_write_scope(...)` 在**取文件锁与读字节之前**执行，越界抛 `FileServiceError(error_type="write_scope_violation")` | `src/llm_loop/workspace/file_service.py`：`edit()` 内、`observe()` 内各一处调用（行号随并发会话改动漂移，按函数名定位） |
| 工具层 | `edit_file` 工具把当前会话 scope 透传给服务层：`write_scope=current_write_scope.get()` | `src/llm_loop/tools/builtin/edit_file.py` |
| 子代理层 | 子会话 scope = 父 scope ∩ 声明 scope；解析不出则 fail-closed 拒绝，不静默忽略声明 | `src/llm_loop/subagent/runner.py`（scope 解析与 `current_write_scope.set(...)`） |
| 未提交面 | 设计文档 `docs/DESIGN-20261030-write-scope-and-concurrent-writer-ownership.md`、`src/llm_loop/core/write_scope.py`、两个测试文件均为**未跟踪新文件**；`file_service.py` 的接入改动亦未提交 ⇒ 断言里的「文档说」指的是**未提交的 WIP 模块 docstring**，与 HEAD 无对应关系 | `git status --short` |

## 2. 两条独立验证

1. **并发会话的测试套件**：`.venv/bin/python -m pytest tests/test_write_scope_enforcement.py tests/test_write_scope_spawn.py -q` ⇒ **38 passed**，含「应拦输入」用例：越界写被拒且**字节不变**、`paths: []` 只读子代理拒写、symlink 逃逸拒写、`..` 穿越拒写、deny 优先于 allow、dry_run 不写审计记录、`observe()` 同一错误类型。
2. **我自写的独立探针**（第二来源，避免"只信一家的测试"）：`scripts/verification/write_scope_gate_probe.py` ⇒ **9/9 PASS，exit 0**。覆盖：正控制（范围内必须放行，防"一律拒绝"式假闸）+ 5 类应拦输入（越界 / 空 paths / symlink 逃逸 / `..` 穿越 / deny 模式）+ 旧行为不变（`write_scope=None` 仍放行）+ 读侧同闸（`observe()` 越界读被同一错误类型拒绝）+ 拒绝后无半成品文件。

## 3. 残余风险（非本项缺口，属特性边界，按设计如此）

1. **特性未提交**：HEAD 上没有任何写侧 scope 闸；若该 WIP 被回滚或丢失，缺口复现。
2. **`execute_command` 是设计已声明的逃逸口**：设计文档明示「不提供安全沙箱」；C8 只做命令串里**字面绝对路径**检查 + `scope_unverified` 审计，P1-b（capability 移除）未实现 ⇒ 受限子代理仍可经 shell 写越界文件（**归属失效，不丢数据**）。
3. **读侧不受工具层约束**：`read_file` 不传 scope ⇒ `paths: []` 子代理仍可读整个工作区。设计口径是 scope = **写侧归属**，读侧按 FR-4 保留只读子代理的读取能力——这是选择，不是漏洞，但容易被读成"读写都收紧了"。

## 4. 处置

- **未改运行时代码**：被指出的缺口不是我的改动，且已由并发会话补上；我的处置是「核实 + 留下可复跑的独立证据」。
- 产出：`scripts/verification/write_scope_gate_probe.py`（可复跑，exit 0 = 闸成立）+ 本记录。
- 提醒：该特性属**并发会话的在途 WIP**，落地前仍需它自己的独立审查与提交；本记录只覆盖「`edit()` 是否绕过 scope 闸」这一个断言。

## 5. 后续状态更新（2026-10-30 15:20，接管会话补记）

本记录以上内容是 **12:54–13:10 的时点事实**，不因后续进展自动失效；以下为后续实测，供读者对齐：

| 项 | 后续事实 | 依据 |
|---|---|---|
| §3-1「特性未提交」 | **已不成立**：特性已实现并提交，HEAD `566e5b09f` 已推 `origin/main`（提交 `ab86dde5b` / `038a0821e` / `566e5b09f`） | `git log --oneline -3`、`git rev-list --count origin/main..HEAD` = 0 |
| 独立探针 | 在最终树上复跑 **9/9 PASS, exit 0**（2026-10-30 15:20），闸仍成立 | `.venv/bin/python scripts/verification/write_scope_gate_probe.py` |
| §2-1 测试数字「38 passed」 | 该数字是 12:54 时点两文件的快照；后续扩到 4 个测试文件，2026-10-30 14:36 复跑为 **141 passed / 1 skipped**，最终树的数字见设计文档 §14 | 设计文档 §12.4 / §14 |
| §3-2 `execute_command` 逃逸口 | **仍然成立**（C8 未实现，shell 通道不受写侧 scope 约束），未因提交而改变 | 设计文档 §9 / §12.5 |

本补记只更新状态对齐，不改动上方任何历史陈述。
