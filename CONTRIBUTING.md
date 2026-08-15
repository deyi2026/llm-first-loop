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
   SoT 再同步 `src/llm_loop/core/prompt.py`（防漂移测试 `test_ai_rules_sync`
   会校验，改了 SoT 不同步会挂）。
5. **公开面原则**：非必要文档不公开——开发过程文档（specs/内部记录）留本地；
   公开仓库只放运行必需 + 面向使用者的内容。

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

## 路线图

见 `docs/ROADMAP-B-20260814.md`（P1 可用性 / P2 差异化 / P3 社区化）与 `CHANGELOG.md`。
欢迎在 issue 讨论新方向后再动手大改。

## 发布流程（B11 月度节奏）

1. **PR 标题规范**：`feat:` / `fix:` / `docs:` / `chore:` / `test:` / `refactor:` / `perf:` 前缀
   ——Release Drafter 按前缀自动归类 changelog 草稿（`.github/release-drafter.yml`）。
2. **PR 合并后**：`release-drafter.yml` 工作流自动更新 Draft Release（草稿，无副作用）。
3. **发版（维护者）**：
   - 核对 Draft Release 内容 → 与 `CHANGELOG.md` 最新段一致（公开面原则：只含使用者可见变更）
   - 打 tag：`git tag vX.Y.Z && git push origin vX.Y.Z`（触发 `release.yml`：门禁复核 + 生成 Release 草稿）
   - 人工确认发布 Release；同步更新 `CHANGELOG.md` 版本段与 `pyproject.toml`/web 版本号
4. **版本语义**：0.x 内小版本可增补能力，不破坏既有行为；公共 API 语义变更必须升版本
   （`docs/api.md` §1 稳定声明 + 签名快照测试保护）。
