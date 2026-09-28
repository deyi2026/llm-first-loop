# Code-Nav Hardening v1 — 可信边界、协议正确性与生产发布方案

- 日期：2026-09-28
- 状态：**REVIEWED / READY FOR IMPLEMENTATION**
- 范围：`scripts/code_nav.py`、`skills/code-nav/SKILL.md`、对应测试与分析文档
- 当前生产基线：generation 159 / `889634f21c5f50b3859a9217949b9c24d437185a`
- 当前主仓 HEAD：`8454c8a9813947173bc5696dcb5d5309d21cdf3b`
- 当前关系：`main...prod = 2 / 46`，merge-base=`393292a3a3cf30fdd1b6c19f794bccb7bb6de108`
- 结论：**保留“按需 Pyright LSP、零常驻索引”方向，但当前未跟踪实现不能直接 commit/上线。先按本文收敛 correctness，再作为独立 generation 发布。**

---

## 0. 执行摘要

本方案不是把 `code_nav.py` 做成“repo 全量引用真相”。它的正式定位应当是：

> **带显式可信度边界的、Pyright 驱动的 Python 语义导航器。**

它负责给出：

1. **已确认 readiness 后**的 LSP semantic locations；
2. 这些结果在哪个 Pyright program/config scope 下成立；
3. 独立的 repo-visible lexical candidates，用于暴露 scope 之外可能需要人工复核的文本命中；
4. callers/callees 的真实调用点、定义点和路径，不混淆语义；
5. 对“不能证明完整”的地方明确 fail-closed 或降级，不把 caveat 包装成成功。

本轮审查后，当前实现至少有 5 个 correctness blocker：

1. readiness 未 fail-closed；
2. cross-check 的“范围外”算法/命名不正确，并混入 ignored/generated 数据；
3. `callees` 跨文件 `site_line` 与路径拼接错误；
4. root/cwd 路径基准混用；
5. 682 行 LSP 客户端没有自动化协议测试。

另有 4 个设计级问题必须一起收口：

- 同名符号定位歧义会静默选第一个；
- callHierarchy 只保留第一个 `fromRange`，会丢多调用点；
- managed worktree 没有 `.venv`，当前 skill 示例在生产代码根不可执行；
- 当前 `main` 与生产分叉较大，不能从 `main` 直接发布，也不能把生产 46 个提交隐式 merge 回 main。

因此 v1 的目标不是“多加能力”，而是：**让每个成功结果都能说明自己为什么可信，让每个不可信结果都不能伪装成成功。**

---

## 1. 已验证事实：哪些结论成立，哪些必须撤回

### 1.1 成立的协议与性能事实

当前环境：Pyright `1.1.411`。

下表中的 repo 数字均来自当前主仓 HEAD `8454c8a9813947173bc5696dcb5d5309d21cdf3b`；它们不是 gen159 production worktree 的固定事实。hardening 原型移植到 production-based worktree 后必须重新测量，不能直接沿用这些 exact counts 作为验收门。

| 事实 | 当前证据 | 结论 |
|---|---|---|
| `initialize` 后必须发送 `initialized` | 三文件 fixture 曾复现：漏发后服务接受握手但后续请求静默挂死 | **保留为协议硬约束** |
| server→client 带 `id` 的消息必须应答 | 已踩到 `window/workDoneProgress/create` 类请求；当前客户端已提供应答路径 | **保留为协议硬约束** |
| readiness 不等会严重假阴性 | `initialize` only = 0/0；didOpen 不等 = 1/1；等 diagnostics = 726/82 | **保留，但限定为当前 Pyright 已验证信号** |
| `refs ToolResult` 主结果稳定 | 3 次独立复验：726 locations / 82 files，ready=true，0.55–0.64s | **当前 repo baseline，可记录，不可当永恒断言** |
| `callers workspace_base` 正确 | 20/20 `site_line` 与定义行逐条回读正确 | **incomingCalls 路径模型可保留** |
| 按需 LSP 低常驻成本 | 每次起停进程，无 daemon/index/tool-schema 常驻 | **架构方向保留** |

注意：当前 `refs` 请求使用 `includeDeclaration=true`，因此“726”是 **semantic locations（包含 declaration）**，不应写成“726 个纯调用/引用点”。

### 1.2 已撤回/修正的事实

| 旧说法 | 复核结果 | 新口径 |
|---|---|---|
| `references(ToolResult)` 608 / 77，冷 2.4s | 无法复现；当前稳定 726 / 82 | 旧数字作废 |
| callHierarchy 行号普遍不可信 | 误把 `selectionRange` 定义行与 `fromRanges` 调用行互比 | callers 的两类行号语义分开后 20/20 正确 |
| 范围外另有 222 行 / 67 文件 | 算法混入 `.codeartsdoer` ignored 快照、`src` 内 lexical-only 命中和非 repo-visible evals | 旧数字不得进入正式 skill |

### 1.3 cross-check 的真实复核结果

当前实现会扫描所有非 `SKIP_DIRS` 的 `.py`，然后跳过“已经出现在 LSP 结果里的文件”。这不等价于“program scope 外”。

实际复核：

- 当前工具输出：222 occurrences / 67 files；
- 其中 `.codeartsdoer` = 78 occurrences，且被 `.gitignore` 明确忽略；
- `src` 内还有 3 occurrences，被错误叫成“范围外”；
- 按 `git ls-files -co --exclude-standard -- '*.py'` 构造 repo-visible Python universe，并真正排除 `src` 后：
  - **137 lexical occurrences / 43 files**；
  - tests=116，scripts=17，examples=4。

这 137 也只能叫 **lexical candidates**，不能叫“Pyright 漏掉的 references”，因为其中可能是注释、字符串、同名符号或其它非语义命中。

### 1.4 `callees` 已证实存在路径/行号伪定位

当前 outgoing call 共用 incoming 的行号拼装模型：

- target path 取 `entry["to"].uri`；
- `site_line` 却取 `entry["fromRanges"]`。

但 outgoing call 的 `fromRanges` 属于**当前 caller 文档**。

真实例子：

```text
工具当前输出：src/llm_loop/config.py:397 -> ensure_dirs
真实调用点：src/llm_loop/factory.py:397 -> settings.ensure_dirs()
```

这是 correctness bug，不是文案问题。

### 1.5 当前实现还丢失多个调用点

对 `factory.py::build_engine` 的真实 Pyright outgoingCalls：

- 344 outgoing entries；
- **82 个 entry 的 `fromRanges` 数量 > 1**；
- 有的同一 callee 有 28 个调用点。

当前实现只保留 `(fromRanges or [{}])[0]`，因此会静默丢调用位置。

### 1.6 cwd/root 混用会让 cross-check 数字爆炸

从 repo root 调用 `refs ToolResult`：726/82，cross-check 222/67。

从 `scripts/` 子目录调用同一命令：LSP 仍是 726/82，但 cross-check 变成 **963 / 149**。

根因：

- `ref_to_row()` 用 `os.getcwd()` 生成相对路径；
- `cross_check()` 用 repo root 生成相对路径；
- known set 因基准不同无法匹配。

所有路径必须统一以 resolved repo root 为基准。

### 1.7 readiness 当前仍会“成功地失败”

强制 `--ready-timeout 0`：

```text
doctor: ok=true, readiness=false, rc=0
refs:   readiness=false, 1 location / 1 file, rc=0
```

这正是本工具最应该禁止的模式：**机器接口成功，但结果静默严重不完整。**

### 1.8 当前 skill 在 managed worktree 中不能按文档示例运行

现有 skill 示例：

```bash
PY=.venv/bin/python
$PY scripts/code_nav.py ...
```

实测当前 managed worktree：

```text
.worktrees/web-auth-mobile-cookie-20260928/.venv            不存在
.worktrees/web-mobile-copy-hardening-20260928/.venv        不存在
.worktrees/chatgpt-binding-notify-outlet-20260928/.venv    不存在
runtime root .venv                                          存在
runtime root .venv/bin/pyright-langserver                   存在
```

所以“skill 出现在 `skill_list`”不等于“skill 里的命令可执行”。v1 必须解决共享 runtime venv 的发现问题。

---

## 2. 两轮 grill_me 后的设计收敛

本方案用 LFL 内置 `grill_me` 的五类问题做了两轮压力测试：`edge_cases / failure_modes / scale / security / ux`。下面只保留会改变实现的结论。

### 2.1 Edge cases：哪些输入必须拒绝而不是猜

| 拷问 | 结论 |
|---|---|
| file 为空、不存在、目录、非 `.py` 怎么办？ | 参数错误，rc=1；不发 LSP 请求 |
| file 指向 repo 外或 symlink 逃逸怎么办？ | 默认拒绝；输入文件 realpath 必须位于 repo root 内 |
| symbol 同一文件出现多个定义怎么办？ | **不能选第一个**；返回 ambiguity，要求 `--line` |
| 只有调用点、没有唯一 def/class/assign 怎么办？ | 若 lexical candidate 多于 1，fail-closed；提供候选行 |
| `prepareCallHierarchy` 返回多个 item 怎么办？ | 不取 `[0]`；返回 ambiguity/candidates |
| `fromRanges` 有多个怎么办？ | 全部保留，不能只取第一个 |
| include 配置是复杂 glob 怎么办？ | 不伪装成“精确 program scope”；原样回执配置，lexical 分类标注 classifier 状态 |
| Pyright 升级怎么办？ | doctor 回执 server version；基线数字不作为硬测试；真实 fixture 必须重跑 |

### 2.2 Failure modes：什么情况下必须 fail-closed

以下任一条件发生，semantic query 不得 rc=0：

1. initialization 失败；
2. `initialized` 无法发送；
3. reader thread/frame parser 崩溃；
4. langserver 提前退出；
5. readiness signal 超时；
6. required capability 不存在；
7. symbol/prepare item 歧义未消除；
8. 默认启用的 repo lexical cross-check 无法完成且调用方没有显式 `--no-cross-check`。

禁止的降级方式：

- 返回空列表并 rc=0；
- 返回一两个早期结果并只加 warning；
- 把 unknown server request 当作成功 `null`；
- 把 lexical text 命中改名为 semantic reference。

### 2.3 Scale：零常驻不代表允许并发起 100 个 langserver

最先爆的不是磁盘，而是进程/CPU/RSS。

v1 保留“无常驻 daemon / 无持久索引”，但增加 **repo-scoped advisory lock**：

- 默认同一 repo 同时最多 1 个 code-nav langserver；
- 其它调用等待 bounded timeout；
- 超时返回 `busy`，不再启动额外 server；
- lock 放 `/tmp`，key=canonical repo root hash，不写 repo 内容。

不引入 cache。原因：当前价值恰恰来自“不会因为缓存/索引陈旧而撒谎”。若以后性能成为问题，另开版本讨论 warm worker，而不是偷偷加缓存。

### 2.4 Security：这是导航 CLI，不应扩大文件读取与进程执行边界

v1 安全边界：

- 输入文件默认限制在 repo root；
- 不接受用户传任意 langserver shell command；
- `subprocess` 始终使用 argv，不走 shell；
- server→client 只 allowlist 已支持请求；未知 request 回 JSON-RPC `MethodNotFound`，不能假装成功；
- 输出不打印文件全文，只打印位置、符号和有限诊断；
- lexical scan 只扫描 `git ls-files -co --exclude-standard -- '*.py'` 的 repo-visible Python 文件；
- ignored 临时快照、worktree、副本、data 默认不进入统计；
- 不写索引、不修改源文件、不持久化源码内容。

### 2.5 UX：30 秒内必须知道“我能信到哪里”

人类输出第一行应回答三件事：

```text
READY | semantic=726 locations/82 files | scope=pyright(include=['src']) | lexical-complement=137 occurrences/43 files
```

若不可信，第一行必须变成失败：

```text
NOT_READY | no semantic result accepted | reason=publishDiagnostics timeout
```

不能把最关键 caveat 藏在最后一行。

---

## 3. 正式产品契约：三层“可信度”，不再声称 repo 全量真相

### 3.1 第一层：analysis readiness

`analysis_ready=true` 是 semantic query 的前置条件。

当前 Pyright 1.1.411 已验证信号：

```text
initialize response
  -> initialized notification
  -> textDocument/didOpen(target)
  -> target URI 的 textDocument/publishDiagnostics
```

重要限制：`publishDiagnostics` **不是 LSP 规范定义的“workspace 索引完成”通用信号**。当前真实 Pyright 采样中 initialize 后只观察到 `workspace/configuration` server requests，didOpen 后收到 target 的 diagnostics，没有更强的 progress-end 信号。因此 v1 必须把它写成：

> **Pyright 1.1.411 上经召回对照验证的 readiness heuristic/contract**，不是跨 LSP server 的协议真理。

这也是为什么真实 Pyright fixture 必须长期存在。

### 3.2 第二层：semantic scope

LSP 结果只声明：

> 在当前 Pyright program/configuration 下，server 返回了这些 semantic locations/calls。

输出应包含：

- config source；
- raw `include`；
- raw `exclude`；
- Pyright version；
- target file；
- readiness signal；
- `includeDeclaration` 值。

禁止输出：

- “repo 内一共只有 N 个引用”；
- “没有其它引用”；
- “范围外一定是 Pyright 漏掉”。

### 3.3 第三层：repo-visible lexical candidates

这是独立事实，不与 LSP 语义结果混为一谈。

候选 universe：

```bash
git ls-files -co --exclude-standard -- '*.py'
```

含义：

- tracked Python 文件；
- non-ignored untracked Python 文件；
- 不包含普通 ignored 临时/生成文件。

注意：已经 tracked 的文件即使后来命中 `.gitignore` 规则，仍属于 repo-visible universe；`git ls-files -c` 会保留它们。这是有意行为，避免把“已入库但后来加 ignore”的真实代码静默排除。

输出指标必须精确命名：

- `matching_files`
- `matching_lines`
- `occurrences`
- `by_top_level_dir`

不要再把 occurrence 字段命名成 `lines`。

lexical candidate 只用于提示“这里还有值得人工检查的文本位置”，**不能升级为 semantic missing reference**。

---

## 4. CLI 与机器接口契约

### 4.1 v1 支持命令

保留：

```text
doctor
refs
callers
callees
```

当前文件头宣称的 `def` 子命令实际没有注册。v1 **先删除这条虚假文档**，不在 correctness hardening 中顺便扩功能。definition command 放入后续 v1.1。

### 4.2 公共参数

建议：

```text
--root <repo>
--json
--timeout <seconds>
--ready-timeout <seconds>
--limit <N>
--line <1-based line>         # 消除同名符号歧义
--no-cross-check              # refs only，显式放弃 repo lexical complement
--lock-timeout <seconds>
```

不增加任意 `--langserver-command`，避免把本地 CLI 变成额外命令执行入口。

### 4.3 退出码

保持简单且机器可判：

| rc | 含义 |
|---|---|
| 0 | query 在 readiness/capability/ambiguity gate 后成功，且有 semantic result；默认 cross-check 也成功 |
| 1 | 参数、环境、协议、readiness、capability、ambiguity、cross-check（默认模式）等失败 |
| 2 | readiness 已确认、query 正常完成，但 semantic result 为 0 |

`rc=2` 只能表示“**在当前 semantic scope 内**零结果”，不能表示 repo-wide absence。

### 4.4 JSON schema

增加稳定 schema id：

```json
{
  "schema": "lfl.code_nav.v1",
  "operation": "refs",
  "status": "ok",
  "target": {
    "path": "src/.../message.py",
    "symbol": "ToolResult",
    "line": 173
  },
  "trust": {
    "analysis_ready": true,
    "readiness_signal": "textDocument/publishDiagnostics",
    "pyright_version": "1.1.411",
    "semantic_scope": {
      "config": "pyproject.toml [tool.pyright]",
      "include": ["src"],
      "exclude": null
    },
    "repo_lexical_cross_check": "complete"
  },
  "semantic": {
    "include_declaration": true,
    "locations": []
  },
  "lexical": {
    "universe": "git-visible-python",
    "occurrences": 0,
    "matching_lines": 0,
    "matching_files": 0
  },
  "caveats": []
}
```

`status` 只允许：`ok / no_results / invalid_input / not_ready / ambiguous / protocol_error / busy / cross_check_failed`。

---

## 5. LSP client hardening

### 5.1 生命周期必须完整

固定顺序：

1. spawn；
2. `initialize` request；
3. 处理 initialize 期间 server→client requests；
4. `initialized` notification；
5. `didOpen`；
6. readiness gate；
7. semantic query；
8. `shutdown` request（bounded）；
9. `exit` notification；
10. 等待进程退出；超时才 terminate/kill。

当前 `close()` 直接 terminate，可作为兜底，但不应是正常路径。

### 5.2 server→client request

allowlist：

- `window/workDoneProgress/create`
- `workspace/configuration`
- `workspace/workspaceFolders`
- `client/registerCapability`

未知带 `id` request：

```json
{"error":{"code":-32601,"message":"Method not found"}}
```

不能统一返回 `result:null`，否则等于向 server 虚报“已成功执行”。

### 5.3 reader thread 失败必须可观察

新增共享状态：

- `reader_error`
- `stderr_tail`
- `process_returncode`

`request()` / `wait_notification()` 每个 pump 周期检查：

- 进程是否已退出；
- reader 是否已报 framing/JSON 错误。

一旦发生，立即 fail，不要等满 180s 再说“server 可能仍在分析”。

### 5.4 版本回执

`doctor` 必须报告：

- langserver path；
- pyright version；
- langserver source（code-root venv / git-common-root venv / PATH）；
- required capabilities；
- readiness signal 与耗时。

版本变化本身不硬失败，但会让历史 benchmark 标记为 `baseline_unqualified=true`，真实 fixture 必须重跑后才能更新文档基线。

---

## 6. managed worktree 下的解释器/langserver 发现

### 6.1 现状问题

生产 `CODE_ROOT` 是 `.worktrees/<deployment>`，里面没有 `.venv`；共享 venv 位于 git common/main runtime root。

### 6.2 v1 解析顺序

`find_langserver(code_root)`：

1. `<code_root>/.venv/bin/pyright-langserver`；
2. 通过 `git rev-parse --git-common-dir` 找 git common root，再查 `<common-root>/.venv/bin/pyright-langserver`；
3. `PATH` 中的 `pyright-langserver`；
4. 否则失败。

其中 common root 推导必须 canonicalize，不能相信 cwd。

skill 的调用示例改成：

```bash
python3 scripts/code_nav.py doctor
python3 scripts/code_nav.py refs src/.../message.py ToolResult
```

脚本本身只使用 Python stdlib，但运行依赖不是“纯 stdlib 世界”：**仍依赖 git CLI + 已安装的 pyright-langserver**。文档应改成“零新增 Python 第三方依赖”，而不是模糊地写“纯 stdlib”让人误以为没有外部依赖。

生产验收必须从 managed worktree 跑一次 `doctor`，确认 `langserver_source=git_common_root_venv`（或等价明确来源）。

---

## 7. 符号定位必须处理歧义

### 7.1 当前风险

`locate_symbol()` 目前按 `def -> class -> assign -> any` 找**第一个**命中。

同一个文件内两个 class 都有 `close()` / `run()` 时，会静默选错。

### 7.2 v1 规则

1. symbol 必须是合法 Python identifier；
2. 收集所有 definition-like candidates；
3. candidate=1：自动选；
4. candidate>1：返回 `ambiguous`，列出行号；
5. 用户提供 `--line`：只在该行/附近验证 symbol 后使用；
6. 没有 definition-like candidate 但有 lexical occurrence：若不唯一仍失败；
7. `prepareCallHierarchy` 返回多 item 时同样 fail-closed。

禁止“为了方便”继续取第一个。

---

## 8. refs 与 lexical cross-check 的新算法

### 8.1 semantic refs

在 readiness gate 后调用 `textDocument/references`。

所有 LSP path 统一 canonicalize 后相对 **repo root** 输出；repo 外结果明确标记 external，不生成 `../../..` 风格混淆路径。

### 8.2 lexical universe

候选文件来自：

```bash
git ls-files -co --exclude-standard -- '*.py'
```

然后逐文件扫描 symbol token，并计算：

- occurrences；
- matching_lines；
- matching_files；
- top-level distribution。

### 8.3 分类，而不是“差额=漏报”

输出至少区分：

- `inside_configured_include`；
- `outside_configured_include`；
- `lsp_result_files`；
- `lexical_only_files`。

如果 include 使用无法可靠复刻的复杂 glob，则：

- `include_classifier=partial/unsupported`；
- 仍输出 repo lexical universe；
- 不声称“outside program”。

### 8.4 默认 cross-check 失败策略

默认 `refs` 承诺执行 lexical complement。因此 git/cross-check 失败时 rc=1。

只有用户显式 `--no-cross-check` 时，才允许 semantic result 正常返回，并在第一行标：

```text
repo lexical complement: NOT CHECKED
```

---

## 9. callHierarchy 必须拆分 incoming/outgoing 数据模型

### 9.1 callers / incomingCalls

每条 entry：

```text
caller_definition_path
caller_definition_line
site_path = caller uri
site_lines = all fromRanges
target = requested symbol
```

### 9.2 callees / outgoingCalls

每条 entry：

```text
site_path = requested/current caller uri
site_lines = all fromRanges
target_path = entry.to.uri
target_definition_line = entry.to.selectionRange
target_name
target_origin = repo | stdlib | third_party | external
```

必须保存**全部** `fromRanges`。

### 9.3 人类输出

示例：

```text
factory.py:419,1845 -> providers.py:128 resolve()
```

而不是：

```text
providers.py:419 -> resolve()   # 错：把 caller 行号贴在 callee 文件上
```

### 9.4 external noise

v1 先不隐藏数据，但 human output 应：

- repo targets 优先；
- external/stdlib 汇总在后；
- `--limit` 作用于展示，不裁剪 JSON 原始结果。

后续 v1.1 再考虑 `--repo-only`。

---

## 10. 并发、超时与资源保护

### 10.1 repo-scoped lock

使用 `/tmp/lfl-code-nav-<sha256(canonical-root)>.lock` + advisory flock。

默认：

- 一个 repo 同时一个 LSP client；
- lock wait 有独立 timeout；
- 超时 status=`busy` / rc=1；
- 不后台排无限队列；
- 进程退出后 lock 自动释放。

### 10.2 timeout 分层

不要只保留一个 180s：

- initialize timeout；
- readiness timeout；
- query timeout；
- shutdown timeout；
- lock timeout。

输出分别报告耗时，便于判断慢在哪里。

### 10.3 不做缓存

v1 明确不缓存 semantic 结果和 program index。

若 1000x repo 下性能不够，未来单独评估 persistent warm server；不得在 v1 中偷偷引入，因为那会改变“不会陈旧”的核心性质。

---

## 11. 测试架构：四层，而不是只有 repo 现场回执

### 11.1 Layer A — pure unit tests

覆盖：

- URI/path normalization；
- repo containment / symlink escape；
- symbol candidate/ambiguity；
- include classifier；
- git-visible lexical census；
- occurrences vs matching_lines；
- incoming/outgoing row construction；
- multi-fromRanges；
- external origin classification；
- JSON schema/status/exit code mapping。

### 11.2 Layer B — fake LSP protocol fixture（必须有）

建立纯 stdlib fake server，精确模拟协议状态机。

必须测试：

| Case | 预期 |
|---|---|
| 收到 initialize，但客户端不发 initialized | fake server 不放行 query；客户端测试应暴露失败 |
| server 发 `window/workDoneProgress/create` | client 必须回同 id 的 response |
| server 发未知 request | client 回 -32601，不回 null success |
| framing/JSON reader 崩 | query 立即 protocol_error，不等满 timeout |
| server process 提前退出 | 立即 error，带 returncode/stderr tail |
| diagnostics 永不到 | not_ready / rc=1；不能 query |
| prepareCallHierarchy 多 item | ambiguous / rc=1 |
| outgoing 多 fromRanges | 全部 site_lines 保留 |

这是防止“协议 silent hang 再出现”的最重要自动化资产。

### 11.3 Layer C — real Pyright fixture

独立临时 repo：

- `src/a.py` 定义 symbol；
- `src/b.py` 两次调用；
- `tests/test_a.py` scope 外 lexical use；
- `pyproject.toml [tool.pyright] include=['src']`。

验证：

1. doctor ready=true；
2. refs 得到 src semantic locations；
3. lexical complement 正确发现 tests candidate；
4. callers site path/line 精确；
5. callees 两个 fromRanges 都保留；
6. 从 repo 子目录执行与 root 执行结果一致；
7. ignored `.tmp/` candidate 不进入统计。

### 11.4 Layer D — current repo canary

当前主仓 HEAD `8454c8a9813947173bc5696dcb5d5309d21cdf3b` 的数字只做观测 baseline，不做脆弱断言：

- `ToolResult`: 当前 726 / 82；
- `workspace_base callers`: 当前 20；
- 当前 git-visible outside-include lexical baseline：137 / 43。

测试只断言：

- ready；
- schema/分类正确；
- 抽样行回读正确；
- cross-check 不含 ignored 路径；
- root/subdir 结果同构。

不要断言永远必须 726，因为代码演进本来就会改变引用数。

---

## 12. 文档与 skill 必须同步修正

### 12.1 `skills/code-nav/SKILL.md`

必须改：

1. “纯 stdlib” -> “Python 实现零新增第三方依赖；运行依赖 git + repo 已有 Pyright”；
2. readiness 写成 **Pyright 1.1.411 已验证 contract**，不是通用 LSP 保证；
3. 明确未 ready = 命令失败，不存在“false 但请自己小心用”；
4. 删除 222/67；
5. lexical complement 只叫 lexical candidates；
6. 726/82 标注日期、repo head、Pyright version、`includeDeclaration=true`；
7. 增加 ambiguity / `--line`；
8. callers/callees 明确 `site_path` / `target_path`；
9. 示例改为 managed worktree 可执行方式，不假设 `.venv` 在 code root；
10. 明确动态派发、TS/JS、repo-wide absence 仍不可证明。

### 12.2 `scripts/code_nav.py` 顶部 docstring

- 删除未实现 `def` 命令；
- 不写“结果带范围=完整”；
- 补三层 trust model；
- 补 exit code 语义。

### 12.3 现有分析文档

新增 R10：

- 撤回 `222 / 67 = 范围外缺失`；
- 记录 current repo-visible lexical baseline 137/43；
- 记录 `callees` 路径/行号 bug；
- 记录 readiness rc=0 bug；
- 记录 managed worktree `.venv` 事实；
- 区分“策略结论仍成立”和“第一版 wrapper correctness 未达标”。

R7“CBM 不引入、优先复用 Pyright LSP”的战略结论**无需撤回**；需要重做的是 wrapper 的可信度实现。

---

## 13. 实施顺序

### Phase 0 — 冻结事实，不改 live

1. 当前 3 个原始交付物保持未跟踪；
2. 记录 SHA256，作为 transplant source；
3. 不 `git add`；
4. 不手工复制到 gen159 live worktree；
5. 不修改当前 skill root。

### Phase 1 — 建干净 hardening worktree

**基于当前 production desired HEAD，而不是 main。**

当前应基于：

```text
889634f21c5f50b3859a9217949b9c24d437185a
```

原因：

- main 与 prod 已 `2 / 46` 分叉；
- 从 main 发布会丢掉生产 46 个独有提交；
- 把生产 46 个提交 merge 回 main 又会把 code-nav 项目变成大型 unrelated merge。

操作：

1. 新建 `fix/code-nav-hardening-20260928` worktree；
2. 仅复制三份未跟踪 source artifacts；
3. 用 SHA256 证明 transplant bytes 与 source 一致；
4. main 独有的两个 governance commit 保持独立，不在本任务 cherry-pick。

### Phase 2 — P0 correctness

按顺序：

1. root/path canonicalization；
2. managed-worktree langserver discovery；
3. readiness fail-closed；
4. reader/process fail-fast；
5. server request correctness；
6. ambiguity handling；
7. refs lexical universe/cross-check；
8. callers/callees 独立 schema + all fromRanges；
9. graceful shutdown；
10. repo lock。

先补测试再/同步改实现，避免再次靠人工回忆协议坑。

### Phase 3 — 文档/skill 收口

只有代码与测试稳定后再更新数字和 Skill。

禁止先写“真值数字”再去追实现。

### Phase 4 — clean qualification

最低门：

```text
ruff check
ruff format --check
py_compile
fake-LSP tests
real-Pyright fixture tests
code-nav unit tests
git diff --check
security scan
```

再跑 current repo canary，但 repo 数字只作为 report，不作为 exact-count gate。

### Phase 5 — 单一 commit

建议 commit：

```text
feat(code-nav): harden on-demand pyright navigation
```

commit 应同时包含：

- script；
- tests/fixtures；
- unit/integration tests；
- skill；
- analysis R10；
- 本计划若需要归档。

不拆成“先上脚本、后上 skill”，避免中间 generation 出现 skill/实现不一致。

---

## 14. 发布与 runtime 生效策略

### 14.1 先处理当前 generation lag

当前 Web 已在 gen159；Feishu/Learning 此前仍落后于 Web-only 更新。

**推荐在 code-nav 发布前先把现有服务收敛到当前 desired generation**，理由：

- code-nav 是跨 runtime 的 skill，不应在已有 generation lag 上继续叠发布；
- attribution 更清楚；
- code-nav rollout 若失败，可以确定是新 generation，而不是历史跨代跳跃。

Learning 按既有 idle gate，不强杀在飞 job。

### 14.2 CAS 发布

发布前重新 currentness check：

- desired generation/head；
- candidate clean；
- candidate 是 desired 的线性下一提交或已明确 rebase；
- env / Knowledge binding / Web artifact preflight；
- pending_failed=[]。

若期间已有新 generation，不硬写“gen160”；应 rebase/重新资格后使用最新 expected_generation CAS。

### 14.3 分阶段重启

建议：

1. Web 先切新 generation；
2. 真实 Web/LFL Session 做 `skill_list -> skill_load(code-nav)`；
3. 在 live code root 跑 `python3 scripts/code_nav.py doctor`；
4. 跑 real repo `refs/callers/callees` canary；
5. 通过后 Feishu；
6. Learning idle 后收敛；
7. 最终 lagging=[]。

### 14.4 为什么最终要全服务收敛

`skills_dir` 跟随各 runtime 的 `CODE_ROOT`。`skill_list` 虽然每次扫描目录，但旧进程仍绑定旧 code root。

所以：

> **不重启某个 runtime，就不能声称 code-nav skill 在该 runtime 已上线。**

手工把文件塞进旧 live worktree虽然可能即时被扫描到，但会破坏 deployment identity、回滚和 Git 可追溯性，禁止采用。

---

## 15. 生产验收矩阵

### A. runtime / deployment

- [ ] Web/Feishu/Learning stable generation 相同；
- [ ] live head 相同；
- [ ] `lagging=[]`；
- [ ] `pending_failed=[]`；
- [ ] `service_control verify ok`。

### B. skill availability

- [ ] `skill_list` 出现 `code-nav`；
- [ ] `skill_load(code-nav)` 加载当前 commit 的 SKILL.md；
- [ ] execution facts 的 code_root 与 runtime manifest 一致；
- [ ] 不存在手工未跟踪 skill 文件。

### C. doctor

- [ ] managed worktree 直接执行成功；
- [ ] pyright path 指向 shared runtime/common-root venv 或明确 PATH；
- [ ] version 明确；
- [ ] capabilities true；
- [ ] readiness true；
- [ ] ready=false canary 返回 rc=1。

### D. refs

- [ ] root 与子目录执行结果 semantic locations 同构；
- [ ] lexical cross-check 不含 `.codeartsdoer/.worktrees/data` ignored 噪声；
- [ ] occurrences/matching_lines/files 字段语义正确；
- [ ] `includeDeclaration` 明示；
- [ ] `--no-cross-check` 有明显降级标志。

### E. callHierarchy

- [ ] callers 抽样 >=20 个位置回读正确；
- [ ] callees 跨文件 site_path 指向 caller 文件；
- [ ] target_path 指向 callee 定义文件；
- [ ] multi-fromRanges 全保留；
- [ ] stdlib/third-party origin 分类合理。

### F. failure semantics

- [ ] diagnostics timeout 不产生 rc=0；
- [ ] fake server 提前退出立即失败；
- [ ] unknown server request 回 -32601；
- [ ] ambiguity 不自动选第一个；
- [ ] 并发第二请求被 lock 等待/拒绝，不再起第二个 server。

---

## 16. 回滚策略

code-nav 只读、不改业务数据，因此回滚风险低，但 deployment 仍走正式路径：

1. 不 reset generation；
2. 发布一个新 generation 指回前一 known-good code head（roll-forward rollback）；
3. 受控重启受影响 runtime；
4. 验证 skill_list 不再暴露坏版本；
5. 保留失败 generation 的测试/acceptance evidence。

如果只是 `code-nav` query 自身失败，不允许它阻断 LFL 主任务运行；skill 的使用应 fail-open 到已有 `search_text/read_file/grep` 工作流，但**code-nav 自己的结果必须 fail-closed**。

这两层不要混淆：

> 工具可不用，但不能撒谎。

---

## 17. 明确不做的事

v1 不做：

- CBM/MCP 常驻索引；
- TS/JS LSP；
- 动态 dispatch 的“智能补全”；
- dead-code 判定；
- 架构自动总结；
- semantic code search；
- diff→自动爆炸半径评级；
- persistent warm langserver；
- 自动写文件/重构。

这些都必须独立评估，不能借 hardening 顺手扩 scope。

---

## 18. Definition of Done

只有同时满足下面条件，才能把 `code-nav` 从“实验 wrapper”升级为“verified skill”：

1. readiness false 永不 rc=0；
2. root/subdir 调用结果不因 cwd 改变；
3. lexical cross-check 的 universe 可机械说明且尊重 git ignore；
4. lexical candidate 不再被叫成 missing reference；
5. callers/callees 的 site/target path+line 语义分别正确；
6. 所有 `fromRanges` 被保留；
7. symbol/prepare ambiguity fail-closed；
8. fake-LSP 生命周期测试覆盖 `initialized` 与 server requests；
9. real Pyright fixture 证明 readiness/refs/callHierarchy；
10. managed worktree 可找到 shared Pyright；
11. Skill/脚本/测试/文档同一 commit；
12. 通过标准 generation 发布，不手工修改 live worktree；
13. 生产至少 Web canary 后再全 runtime convergence；
14. 最终 `lagging=[] / pending_failed=[] / verify ok`。

---

## 19. 最终决策

### 保留

- R7：**不引入 CBM，优先复用已有 Pyright LSP**；
- 零常驻索引；
- 按需启动；
- references + callHierarchy 作为 Python 语义导航核心。

### 撤回/重做

- 当前 222/67 “范围外缺失”口径；
- readiness 只 warning 不 fail；
- callers/callees 共用路径模型；
- cwd-relative row path；
- `.venv` 位于 code root 的假设；
- “纯 stdlib=无外部运行依赖”的表述；
- 没测试就把协议经验固化成 skill 的做法。

### 推荐实施路线

> **先把现有 runtime 收敛到统一 baseline；再从当前 production desired HEAD 建 clean hardening worktree；移植未跟踪原型；完成 P0 correctness + fixture tests；更新 Skill/R10；单 commit；Web canary；最后全 runtime convergence。**

这是当前风险最低、证据链最完整、回滚最清晰的路径。
