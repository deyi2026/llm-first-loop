# DSH vs LLM-First Loop 对比分析——自我审查报告

> **审查日期**：2026-08-15
> **审查基准**：无法取得 DSH 原文（头条反爬），改为对"原对比分析中对本仓库代码的 6 条核心论断"做源码级取证核对。
> **核对置信度**：高（6 条全部直接取证，无推断）。
> **触发原因**：用户要求对照 DSH 原文审查原对比分析；原文不可得，转为代码实证自审。

---

## 1. 错误清单

| # | 原分析论断 | 核对结论 | 严重度 |
|---|---|---|---|
| **E1** | "只有 `execute_command` 有 approval/exec_mode，`edit_file`/`web_fetch`/`send_feishu_message` 全裸奔" | **不属实** | 高 |
| **E2** | "Tool 基类只有 execute()，无 pre/post hook，附件/审计/UI 散落，无统一管线" | **部分属实** | 中 |
| ✓ | 覆盖式注册无版本保留 | 属实 | — |
| ✓ | 无 Package 版本分离 | 属实 | — |
| ✓ | dispose() + Cordis disposer 语义 | 属实 | — |
| ✓ | 无约定文件自动收集/无 file_path 增量刷新 | 属实 | — |

---

## 2. 错误详解与修正

### E1：Approval 覆盖范围——原分析严重低估

**原分析说**：`edit_file` 改代码没有任何审批，`send_feishu_message` 裸奔。

**实际**（`src/llm_loop/tools/registry.py:613-615`）：

```python
def _is_destructive_tool(self, name: str) -> bool:
    return name in {"execute_command", "delete_file", "write_file", "edit_file", "append_file"}
```

`edit_file` / `write_file` / `delete_file` / `append_file` **全部在破坏性工具集里**，统一过 `exec_mode`（readonly/allowlist/blocked）+ `approval_callback`（`registry.py:312-345`）。

`send_feishu_message` 虽不在破坏性工具集，但有**独立审计** `_write_audit`（`src/llm_loop/introspection/tools_feishu_outbound.py:208,225`）落盘。

**真正没覆盖的只有**：`web_fetch` 等非破坏性但有外部副作用的工具。

**对建议的影响**：
- 原 P2"Approval gate 全工具覆盖" → **修正为**"Approval 扩展到非破坏性但有外部副作用的工具（`web_fetch` 等）"
- 优先级从 P2 降到 P4（破坏性工具已覆盖，剩余缺口小）

---

### E2：工具管线——原分析说"散落/无管线"，实际管线相当完整

**原分析说**：无 pre/post hook，附件/审计/UI 散落各工具内部。

**实际**：

1. **统一执行管线存在**（`registry.py:244-408`）：参数校验 → 物化边界 → 灾难性安全 → EXEC_MODE → 审批 → pre 钩子 → 执行 → post 钩子 → 输出分层 → 存档
2. **钩子机制存在**（在 registry/pipeline 层）：
   - `registry.py:28,239-241,359-368` → `add_pre_execute_hook` + 瀑布执行
   - `src/llm_loop/tools/pipeline.py:194-203,209-244` → `add_pre_hook` / `add_post_hook` + `run_post_hooks`
3. **`ToolResult` 根本没有 attachments 字段**（`src/llm_loop/core/message.py:95-112`）——原分析说"附件散落"是凭空臆造
4. **审计统一在 registry 层**（`_approval_log` / `safety` / `_archive_oversize_output`），不散落
5. **UI 渲染统一在 `ToolResult.to_message`**（`message.py:114-139`），不散落

**唯一的真实差距**：`Tool` 协议（`src/llm_loop/tools/base.py:17-24`）只声明 `execute()`，钩子在 registry/pipeline 层而非 Tool 基类——这是设计选择（管线在调度层），不是缺失。

**对建议的影响**：
- 原 P3"Tool 加 pre_execute/post_execute 钩子" → **撤销**（钩子已存在于 pipeline 层）
- 改为"评估现有 pipeline 的 post_hook 是否覆盖 DSH 的 post-execute 物化语义（副作用声明/附件物化）"

---

## 3. 遗漏清单

| # | 遗漏项 | 证据 |
|---|---|---|
| **O1** | 原分析没提到 `tools/pipeline.py` 的存在——这是**统一工具执行瀑布**模块，是重要架构资产 | `pipeline.py:194-244` |
| **O2** | 原分析说"exec 工具的分级执行"——实际是**所有破坏性工具**的分级执行，覆盖面比原分析说的大 | `registry.py:649-656` |
| **O3** | 原分析没提到 `unregister()` 有"Cordis reversible effects"注释——与 `dispose()` 成对构成注册即回滚语义 | `registry.py:167-180` |

---

## 4. 修正后的落地建议（按 ROI 重排）

| 优先级 | 改动 | 原建议 | 修正 |
|---|---|---|---|
| **P1** | Registry 加 Package 版本分离 | 不变 | 论断4 属实，建议有效 |
| **P2** | `eval/` 加 hidden task set | 原 P5 | 提升优先级（原 P2/P3 被撤销/降级） |
| **P3** | Approval 扩展到 `web_fetch` 等非破坏性有副作用工具 | 原 P2 修正 | 范围缩小，工作量降低 |
| **P4** | AGENTS.md 自动收集 + file_path 增量刷新 | 不变 | 论断6 属实，建议有效 |
| ~~P3~~ | ~~Tool 加 pre/post hook~~ | **撤销** | 钩子已存在于 pipeline 层 |

---

## 5. 整体评估

| 维度 | 评分 | 说明 |
|---|---|---|
| 概念映射准确度 | 7/10 | DSH 概念映射方向正确，但对"我们"代码的两处论断错误导致映射偏差 |
| 建议可执行度 | 6/10 → **8/10** | 修正后：P1/P2/P4 均有明确代码锚点，撤销了基于错误前提的 P3 |
| 代码实证度 | **2/10 → 9/10** | 原分析未实际核对代码（凭印象）；核对后 6 条全部取证 |
| 诚实度 | — | 主动披露两处错误，未掩盖 |

**核心教训**：原分析中"凭印象"下的两处代码论断（E1、E2）都高估了"缺失/散落"程度——实际本仓库的 `registry.execute` 统一管线 + `pipeline.py` 瀑布 + 跨破坏性工具 approval 已经相当成熟。**真正的差距集中在"Package 版本分离"（P1）和"hidden task set"（P2）两点**，其余比原先说的要小。

---

## 6. 核对取证索引

| 论断 | 结论 | 关键证据文件:行 |
|---|---|---|
| 1 覆盖式注册无版本保留 | 属实 | `src/llm_loop/tools/registry.py:151-165,59` |
| 2 仅 execute_command 有 approval/exec_mode | **不属实** | `src/llm_loop/tools/registry.py:613-615,312-345,649-656`；`src/llm_loop/factory.py:205`；`src/llm_loop/introspection/tools_feishu_outbound.py:208,225` |
| 3 Tool 基类只有 execute，无钩子/无统一管线 | **部分属实** | `src/llm_loop/tools/base.py:17-24`（属实）；`src/llm_loop/tools/registry.py:239-241,359-368`；`src/llm_loop/tools/pipeline.py:194-203,209-244`；`src/llm_loop/core/message.py:95-112,114-139`（不属实） |
| 4 无 Package 版本分离机制 | 属实 | `src/llm_loop/tools/registry.py:59`；全局 grep 零匹配 |
| 5 dispose() + Cordis disposer 语义 | 属实 | `src/llm_loop/tools/registry.py:182-191,167-180` |
| 6 无约定文件自动收集/无 file_path 增量刷新 | 属实 | `src/llm_loop/core/prompt.py:85-95,12-82`；`src/llm_loop/core/loop/engine.py:839,832-891` |