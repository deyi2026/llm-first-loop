# EVO-20261030-109d7068 — 冻结产物头部字段粘连：修复与实测回执

## 1. 触发来源与授权
- **缺陷来源**：push 准入独立审查 P2-1（候选 SHA256 `dde36126…abcc`，冻结区间 `144e49355→785e5a2e5`；第二版候选 `784635e2…9185` 头部同为该格式）。
- **人工授权**：EVO-20261030-109d7068 于 2026-10-30 15:48 在 web 面板批准；运行时状态 `executing`（来源：`search_records(kind=evolution / evolution_exec)`，建议正文 371 字符已全文核对）。
- **建议要点**：头部改为每字段一行的稳定格式；生成后加一条自检——断言头部能被**自身解析器**往返解析一次，解析失败即**拒绝出票**（避免"看起来在工作"的格式缺陷）。

## 2. 缺陷（修复前）
`src/llm_loop/tools/review_host_admission.py::_source_snapshot` 旧实现把头部字段直接拼接：

```python
base_line = f"push_remote_base={base}"          # ← 无尾随换行
head_line = f"frozen_head={frozen_head}\n"
first_push_line = f"push_first_push_anchor={base} push_target_ref={ref}\n"  # ← 空格分隔两字段
material = (f"repo_head={head}\n{base_line}{head_line}{first_push_line}{excludes_line}" ...)
```

结果：`push_remote_base=<sha>frozen_head=<sha>` 落在同一行，一行两字段。人可手工切分两个 40 hex，机器解析必然歧义。

## 3. 修复内容
### 3.1 头部序列化 / 解析 / 往返自检
- `_FROZEN_HEADER_KEY_RE`（键名 `[a-z][a-z0-9_]*`）、`_FROZEN_HEADER_GLUE_RE`（值以 `<key>=` 开头 = 粘连形状）、`_FROZEN_MATERIAL_BODY_MARKER`。
- `_frozen_header(fields)`：每字段一行 `key=value`；拒绝 None 值、值内空白、粘连形状、重复键。
- `_parse_frozen_header(text)`：一行一字段严格解析；空行忽略；键名非法、值内空白、值以 `<key>=` 开头、重复键 → 全部**拒绝**（fail-closed，不猜）。
- `_frozen_header_block(material)`：切出 material 头部块；`_assert_frozen_header_roundtrip(header, expected)`：解析结果必须与预期字段**完全相等**，否则抛 `review_frozen_header_malformed:round_trip_mismatch`。
- 值中间的 `=` 合法（refname 可含 `=`，如 `refs/heads/a=b`）：解析在**第一个** `=` 处切分。

### 3.2 出票链路
- `_frozen_header_fields(...)` 组装字段列表；`_frozen_material(...)` 组装 material 并**对组装结果**做往返自检；`_source_snapshot` 调用二者。
- 不通过即抛 `ValueError(review_frozen_header_malformed:…)` → `start()` 返回 `{"accepted": False, "reason": …}`，审查子进程**不启动**（拒绝发生在出票前）。
- 字段名、字段含义、字段顺序与修复前一致（`repo_head` / `push_remote_base`｜`merge_base` / `frozen_head` / `push_first_push_anchor` / `push_target_ref` / `runtime_output_excludes`），仅分隔符与行结构改变。

### 3.3 函数尺寸棘轮（R9）
- 本轮把头部拼装逻辑从 `_source_snapshot` 抽到模块级 helper：`_source_snapshot` AST 实测 **193 → 173 行**（基线登记 177）。
- 副作用：HEAD 上另一会话遗留的 `_source_snapshot` 178 行越线（登记 177 → 实测 178）被本重构一并消除；`tests/unit/test_arch_guards.py` 由红转绿（40 passed）。

## 4. 实测回执（RULE-AI-35：必须实测"应拦输入"确被拦下）
1. **定向测试（整文件）**：`.venv/bin/python -m pytest tests/unit/test_review_host_admission.py -q` → `156 passed`。
2. **新增/相关用例（-v）**：
   - `test_frozen_header_puts_one_field_per_line` PASSED
   - `test_frozen_header_parser_refuses_legacy_glued_format` PASSED
   - `test_admission_refuses_to_issue_glued_header` PASSED
   - `test_full_test_header_uses_merge_base_line` PASSED
   - `test_full_test_refuses_to_issue_glued_header` PASSED
3. **真实入口拦截**（`test_admission_refuses_to_issue_glued_header` / `test_full_test_refuses_to_issue_glued_header`）：把序列化器替换回 EVO 前的粘连形状后，真实 `HostReviewAdmission.start(kind="git_push")` 与 `start(kind="full_test")` 均返回 `accepted=False`，`reason` 含 `review_frozen_header_malformed` **且精确到 `glued_value`**（证明拒绝来自粘连检测本身，而不是正文标记缺失），且 `runner.started == 0`（审查子进程从未启动）。
4. **形状对照（模块函数级）**：

```
NEW header (每字段一行):
  | repo_head=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  | push_remote_base=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  | frozen_head=cccccccccccccccccccccccccccccccccccccccc
NEW parsed: {'repo_head': 'aaaa…', 'push_remote_base': 'bbbb…', 'frozen_head': 'cccc…'}
LEGACY header (EVO 之前):
  | repo_head=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  | push_remote_base=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbfrozen_head=cccccccccccccccccccccccccccccccccccccccc
LEGACY refused: review_frozen_header_malformed:glued_value:push_remote_base
LEGACY roundtrip refused: review_frozen_header_malformed:glued_value:push_remote_base
```

5. **full_test 路径同样受自检约束**：`test_full_test_header_uses_merge_base_line` 直测 `merge_base` 分支头部逐行可解析（此前全仓无 `merge_base` 头部断言）。
6. **连带回归**（最终形态一次跑完）：
   - 依赖该模块的 5 个测试文件 + 文档/守卫 4 个文件（`test_arch_guards` / `test_docs_search` / `test_english_docs` / `test_ai_rules_sync`）→ `195 passed`。
   - `tests/unit/test_arch_guards.py` 单独 → `40 passed`（R9 棘轮绿：登记 177 → 实测 173）。

## 5. 独立审查回执（3 轮独立只读 GLM-5.3 子代理，隔离会话、不共享本会话上下文）

| 轮次 | 审的对象 | 结论 | 发现 | 收口动作 |
| --- | --- | --- | --- | --- |
| 1 | 首版实现（逐字段一行 + 解析器 + 往返自检） | `VERDICT: PASS` | P0=0 / P1=0 / P2=4 | 解析器收紧为 fail-closed、拒绝 None 值、值内 `=` 的合法性与文档化、补 `merge_base` 分支直测 |
| 2 | 上述收口 + 函数尺寸重构后的形态 | `VERDICT: PASS` | P0=0 / P1=0 / P2=4 | 错误码统一（`bad_value`）、键名正则改 `\Z`、正文标记改为行首匹配、补 full_test 负向对称用例 |
| 3 | 第 2 轮 P2 的落地 delta | `VERDICT: PASS` | P0=0 / P1=0 / P2=1 | P2-1：正文标记改行首匹配后，两个负向用例的拒绝原因会漂移到"正文标记缺失"而非"粘连检测" → 夹具改为粘连+行尾换行，断言精确到 `glued_value` |

- 第 3 轮 P2-1 收口后**未再单开第 4 轮复审**：该 delta 只改测试夹具与断言（不动实现），且是评审自身提出的整改项，已由 §4.1（156 passed）与 §4.3 的真实入口拦截验证。
- 三轮均为独立只读审查（子代理隔离会话、限定工具与只读范围），审查对象与结论逐轮对应上表。

## 6. 边界与本轮未做
- **未跑全量测试**：按 RULE-AI-28，全量测试与 push 各自需要 `review_admission` 的独立审查与一次性资格；本轮只做定向测试与模块级实测。
- **未推送**：push 由接管会话按 `review_admission` 流程走。本轮改动改变了 material 的字节内容，冻结产物身份随之改变 → 以此前的候选（`dde36126…abcc` / `784635e2…9185`）切出的准入结论**不再覆盖新树**，需按新树重切候选再审。
- **并发写者边界**：本轮改动只落在 `src/llm_loop/tools/review_host_admission.py` 与 `tests/unit/test_review_host_admission.py` 两个文件；同期另一会话在同两文件的 WIP（EVO-20261030-62773eae 投影次序修正）已先行提交（`90fad9ab6`），本轮差异经 `git diff --stat` 核对只含本轮改动，未夹带他人改动；仓库根的未跟踪过程物（`.tmp-*`、`reports/qualification-r4/mech-all-sample.json` 等）未触碰、未入库。
