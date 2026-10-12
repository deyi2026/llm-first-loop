---
name: code-nav
description: 使用仓库已有的 Pyright language server 做 Python 跨文件语义导航。用于改函数前确认调用者/被调用者、收敛 grep 结果到真实语义引用、检查符号爆炸半径，或在陌生模块里追踪引用链。必须通过 readiness gate 才接受语义结果；把 LSP semantic scope 与 repo-visible lexical candidates 分开报告；遇到符号歧义、协议错误、server 提前退出或未就绪时 fail-closed。常用入口：scripts/code_nav.py doctor / refs / callers / callees。
---

# code-nav — 按需 Pyright 语义导航

## 核心原则

1. **先证明 ready，再信结果。** `initialize -> initialized -> didOpen -> publishDiagnostics(target)` 是当前 Pyright 1.1.411 已验证的 readiness contract。未收到目标文件 diagnostics 时命令必须失败并返回非零；不要采用部分结果。
2. **区分 semantic 与 lexical。** LSP 结果只声明在当前 Pyright program/config scope 内成立。`refs` 默认另跑 repo-visible lexical cross-check；这些文本命中只能叫 lexical candidates，不能直接叫“Pyright 漏掉的 references”。
3. **调用点和定义点分开。** `callers`/`callees` 输出 `site_path/site_lines` 与 definition/target path；必须保留全部 `fromRanges`，不要只看第一个调用点。
4. **歧义就失败。** 同文件多个同名 definition、或 `prepareCallHierarchy` 返回多个 item 时，不允许自动选第一个。
5. **路径以 repo root 为准。** 从仓库根或子目录执行应得到同一 semantic 结果；目标文件必须位于 repo 内且为 Python 文件。

## 运行依赖

`code_nav.py` 的 Python 实现不新增第三方包，但运行依赖：

- `git` CLI；
- 已安装的 `pyright-langserver`。

managed worktree 通常没有自己的 `.venv`。脚本会按以下顺序找 language server：

1. 当前 code root 的 `.venv/bin/pyright-langserver`；
2. Git common root 的共享 `.venv/bin/pyright-langserver`；
3. `PATH`。

不要在 Skill 里假设 `$PWD/.venv` 一定存在。

## 用法

```bash
# 0) 自检：server / version / config / capability / readiness
python3 scripts/code_nav.py doctor

# 1) 谁调用它
python3 scripts/code_nav.py callers src/llm_loop/core/run_context.py workspace_base

# 2) 它调用谁
python3 scripts/code_nav.py callees src/llm_loop/factory.py build_engine

# 3) 语义引用 + repo-visible lexical complement
python3 scripts/code_nav.py refs src/llm_loop/core/message.py ToolResult --limit 20

# 4) 机器可读
python3 scripts/code_nav.py refs src/llm_loop/core/message.py ToolResult --json
```

退出码：

- `0`：readiness/capability/ambiguity gate 后成功，且有 semantic result；
- `1`：参数、环境、协议、readiness、ambiguity、repo lock 或默认 cross-check 失败；
- `2`：readiness 已确认且查询正常完成，但当前 semantic scope 内结果为 0。

`rc=2` **不能**解释成 repo-wide absence。

## 机器输出怎么读

成功 JSON 使用 `schema=lfl.code_nav.v1`，重点看：

- `status`: `ok` / `no_results` / `not_ready` 等；
- `trust.analysis_ready`；
- `trust.readiness_signal`；
- `trust.semantic_scope`；
- `trust.repo_lexical_cross_check`（`refs`）；
- `cross_check.universe=git-visible-python`；
- `cross_check.occurrences / matching_lines / matching_files`；
- `inside_configured_include` / `outside_configured_include`。

lexical universe 来自：

```bash
git ls-files -co --exclude-standard -- '*.py'
```

即 tracked Python + non-ignored untracked Python。普通 ignored 临时/生成文件不进入统计。

## 2026-09-28 hardened 基线

环境：production-based hardening worktree，base gen159 `889634f21...`，Pyright `1.1.411`。

| 操作 | 当前观测 |
|---|---|
| `doctor` | `status=ok`、ready=true、`langserver_source=git_common_root_venv` |
| `refs ToolResult` | **729 semantic locations / 82 files** |
| root vs `scripts/` 子目录执行 | semantic locations 完全一致 |
| lexical complement | **153 occurrences / 153 lines / 47 files** |
| configured include=`src` 内 lexical-only | 3 occurrences / 3 files |
| configured include 外 lexical-only | **150 occurrences / 44 files** |
| `callers workspace_base` | 21 callers |
| `callees build_engine` | 361 outgoing entries；多 `fromRanges` 完整保留 |
| `--ready-timeout 0` | rc=1 / `status=not_ready` |

这些数字是**当前代码快照的观测 baseline，不是固定验收门**。代码演进后 exact counts 变化是正常的；必须保留的是 readiness、路径、scope、分类和字段语义。

## 协议硬约束

- `initialize` 成功后必须发送 `initialized`；漏发可表现为静默挂死。
- server→client 带 `id` 的消息是 request，必须应答。
- 已支持 request 走 allowlist；未知 request 返回 JSON-RPC `-32601 Method not found`，不要假装 `result:null` 成功。
- reader framing/JSON 错误或 server 提前退出必须 fail-fast，不等满 query timeout。
- 正常结束走 `shutdown -> exit`，terminate/kill 只作兜底。
- 同一 repo 默认用 advisory lock 限制并发 langserver，避免瞬时 fan-out。

## callers / callees 字段语义

`callers`：

- `site_path/site_lines`：caller 内真实调用点；
- `caller_definition_path/caller_definition_line`：caller 定义位置。

`callees`：

- `site_path/site_lines`：当前 caller 文件里的调用点；
- `target_path/target_definition_line`：被调用函数定义位置。

例如真实 hardened canary 已得到：`factory.py:397 -> config.py:731 ensure_dirs()`；这避免了旧原型把 caller 行号错误贴到 callee 文件上的伪定位。

## 已知盲区

1. **动态派发仍解不了**：`getattr`、注册表、字符串 dispatch 等要沿注册结构追踪。
2. **只覆盖 Python**：TS/JS 尚无对应 LSP wrapper。
3. **readiness signal 是版本限定 contract**：`publishDiagnostics` 不是 LSP 规范定义的“workspace 全索引完成”通用保证；当前结论基于 Pyright 1.1.411 的 fixture 与真实仓库对照。升级 Pyright 后要重跑真实 fixture/canary。
4. **零常驻有启动成本**：每次调用都会重建 program；不要在高频循环里调用。
5. **semantic scope 不是 repo 全量真相**：即使 `status=ok`，也只说明当前 Pyright program scope 内的语义结果成功。需要 repo 级排查时同时看 lexical complement。

## 固定核验动作

在高风险修改前：

```bash
python3 scripts/code_nav.py doctor --json
python3 scripts/code_nav.py refs <file> <symbol> --json
python3 scripts/code_nav.py callers <file> <symbol> --json
```

若 lexical candidates 与 semantic results 不一致，回读对应源文件判断它们是注释/字符串/同名符号，还是 program scope 外的真实使用；不要把文本差额直接升级成语义结论。
