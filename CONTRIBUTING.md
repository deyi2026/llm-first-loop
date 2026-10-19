# Contributing（贡献指南）

感谢你考虑为 LLM-First Core Loop 贡献代码。本指南很短——请先读完"项目哲学"，
它决定了这里什么算好贡献。

## 项目哲学（先读，最重要）

1. **程序最小化**：能用文档规则 + AI 自主完成的判断，不写进程序。代码只保留
   AI 无法自完成的部分（工具真实执行、存储、灾难性安全硬边界）。
2. **如实反馈**：工具成功/失败/异常如实标注（`[状态: xxx]`），错误完整透传，
   不静默降级、不伪装成功。
3. **容错优先**：组件故障 → `[程序异常]` 如实告知 → 循环继续。
4. **规则真相源（SoT）**：`docs/ai_rules.md` 是唯一规则真相源；规则改动先改
   SoT，并核对受影响的实现、工具契约与测试。`test_ai_rules_sync` 断言
   universal prompt 不得镜像规则 playbook；不要把规则全文同步进 `prompt.py`。
5. **公开面原则**：非必要文档不公开——开发过程文档（specs/内部记录）留本地；
   公开仓库只放运行必需 + 面向使用者的内容。

## 开发/修复防退化必读

任何修改运行行为、Provider、连续性、历史、缓存、工具、Web、SubAgent 或存储的贡献，在动代码前先读 `docs/DEVELOPMENT_REPAIR_SAFETY.md`。其中的六问硬门要求先确认 exact source/可恢复 ref、真实 provider-view、当前 runtime qualification、程序/模型权责边界，以及最终 staged/isolated candidate 的真实验证口径。LFL 自身对应规则入口为 `RULE-AI-24`。

## 环境与门禁

```bash
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"
# 三件套门禁（PR 前必须全绿，CI 也会跑）：
.venv/bin/python -m pytest tests/ -q -m "not real_llm"   # 全量单测
.venv/bin/ruff check src tests scripts                     # 静态检查
.venv/bin/pyright src --pythonpath .venv/bin/python        # 类型检查
```

- 测试隔离：`tests/conftest.py` 已全局防御真实 `data/` 污染——新测试用 `tmp_path`，
  不要指向真实数据目录。
- real_llm 测试（需要真实 API key）加 `@pytest.mark.real_llm`，不随全量运行。
- 新增/修改行为必须登记到公开 `CHANGELOG.md`（面向使用者的变更摘要）。

## 如何贡献

### 报告 bug
用 GitHub issue（Bug 模板）。请包含：复现步骤、期望/实际行为、`python -m llm_loop.cli` 版本输出。
**不要**在 issue 里贴 API key / 密钥。

### 提交代码（PR 流程）
1. fork + branch（`fix/xxx` 或 `feat/xxx` 命名）。
2. 改动 + 测试（新功能必须有测试；修 bug 先加复现测试）。
3. 本地三件套门禁全绿。
4. PR 描述：动机 / 改动 / 测试 / 行为影响（是否改变默认行为——零回归优先）。

### 新增工具/技能
- 工具：实现 `name/description/parameters/execute` 协议（见 `docs/api.md` §5），
  description 写"何时用/何时不用/失败对策"三要素。
- 外部技能：直接放 `skills/<name>/SKILL.md`（frontmatter `name`/`description` + 正文），
  零代码即可被 AI 发现（`skill_list`/`skill_load`）。

### 新增评测场景
见 `tests/eval_sets/README.md`（schema + 5 步流程 + 纪律：不程序强制/统计约束/负结果同等呈现）。

## 行为约定

- **零回归优先**：默认行为不变（新配置默认关闭或与旧行为等价）；实在要变，明确说明并升版本号。
- **失败处理**：新代码的异常路径用 fail-open（如实反馈 + 不阻断主流程），
  `except: pass` 必须带注释说明（有静态测试检查裸 pass）。
- **密钥**：密钥只从环境变量读取；代码/文档/日志/审计永不出现密钥字面量。
- **中文注释**：代码注释与文档以中文为主（README 双语）。

## 分支与证据归档卫生（2026-10-17 起）

前缀即意图，两轨制：

- **证据线**：`eval/ experiment/ exp/ qual/ integration/ archive/` 前缀 = 过程证据，
  **默认不合入 main**。收口后打 `evidence/<分支名>` tag 指向原 tip，删除分支与
  worktree；审计入口 `git log evidence/<name>` / `git show evidence/<name>`。
- **产品线**：`feat/ fix/ release/` 前缀 = 需要并入 main 的功能，走下方合并门。
- **合并门（三原则 + 副作用）**：① 功能仍被需要（未被 main 后续演进覆盖）→
  ② 在隔离 worktree 修复至可合、测试全绿 → ③ 副作用评估：对大模型能力/智力/
  执行力的实际收益 vs 冲突面/体积/回退风险。基于旧架构的集成快照不再合入
  （例：dual-agent gen236–238，117 文件 ±2 万行差异、落后 172 commit，其结论
  已以 assurance gate 形式进 main）。
- **清理节奏**：独有 commit ≤4 且 30 天无活动 → 进清理清单；worktree 必须
  dirty=0 才可移除；分支删除前必须先打 tag。
- **并发写防护**：多代理同仓施工时，refs 写操作前后各拍一次快照留证；发现
  对象被并发触碰（ref 忽隐忽现/移动）立即退避该对象，绝不与另一代理同时
  处置同一分支。

## 路线图

见 `docs/ROADMAP-B-20260814.md`（P1 可用性 / P2 差异化 / P3 社区化）与 `CHANGELOG.md`。
欢迎在 issue 讨论新方向后再动手大改。

## 版本与 GitHub 发行流程

版本单一真值是 `pyproject.toml`；完整维护者操作步骤见 [`docs/releasing.md`](docs/releasing.md)。

1. 在**正式仓** `deyi2026/llm-first-loop`（本机 remote `lfl`，不是 legacy `origin`）基于 GitHub `main` 建受审隔离分支；开 PR，保留范围明确的 diff，检查 `CI` 的 pytest/Ruff/Pyright、安全扫描与平台安装验收；不得夹带本地开发 `main` 尚未公开的祖先提交。
2. 用户可见变更同步 `CHANGELOG.md`；对外版本统一修改 `pyproject.toml`、`uv.lock`、Web `SERVICE_VERSION`、中英文 README 及 CHANGELOG，并通过版本一致性测试、独立审查与完整 R9。正式仓 `main` 的合并应从 GitHub 精确已批准的 PR/commit 完成。
3. 核对远端最新 tag，不覆盖或移动已有 `vX.Y.Z`；仅对已合入 GitHub `main`、通过 CI 的精确提交创建新 tag。推送正式仓 tag 会运行**唯一写者** `.github/workflows/release.yml`，先重复校验 tag↔包版本/静态检查/测试，再构建 wheel、sdist、安装脚本、验收 JSON 与 `SHA256SUMS`，生成与 tag 同名的 **Draft Release**。
4. 核对真实工作流结果、Draft 附件、SHA256SUMS 和安装器与 Release API 的兼容性，再由维护者把 Draft 发布为稳定 Release；对用户公开的安装入口 `releases/latest` 只包含已正式发布的版本。旧 Draft（例如缺少附件的旧发行草稿）不得当成成功发行或直接发布。
5. 发布后从真正的稳定 Release 下载并重新校验 wheel/摘要、执行干净 Linux 用户级安装与版本/数据保护检查。已发布 tag/commit 不得修改，修复使用新 patch tag；回滚要明确当前安装实例和用户数据边界，不做静默破坏性覆盖。

发布不等于生产环境部署/服务重启。PR 标题建议使用 `feat:` / `fix:` / `docs:` / `chore:` / `test:` / `refactor:` / `perf:`。当前仅使用 tag 触发的 `release.yml` 写 Draft；旧 Release Drafter 不得再作为并行写入口。
