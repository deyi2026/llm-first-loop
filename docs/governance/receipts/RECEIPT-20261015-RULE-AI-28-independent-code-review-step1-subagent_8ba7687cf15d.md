# 独立审查回执落盘 · RULE-AI-28 代码闸（父代理头部元信息）

- 派遣来源：用户指令 2026-10-15T01:09:35+08:00（普通工作审查派遣；非 Rule31 一次性签署审批，不构成 Provider 放行或安装授权）
- 独立 Reviewer：child_id=subagent_8ba7687cf15d（spawn_subagent 创建，inherit=false 新会话新上下文，未参与被审补丁开发）
- 模型/规模：glm/glm-5.3，rounds=12，tools=42，tokens_in=332538，tokens_out=23770
- 工具约束（E4 强制白名单）：execute_command, inspect_code, read_file, search_docs, search_files, search_records；network=false
- 审阅产物：git staged diff（--no-ext-diff）实测 16716 字节，SHA-256 c67cdf7750417450ed979232842a3f2be274658d5f5e7de4cb42428698802c90，文件清单与期望六文件逐项一致
- 子代理终态原文完整性锚：subagent_result recovery evidence blob SHA-256 19fd458def03ae6bc822796781c7ac739bafe94c5a83ee5a7179f0aee12ff6ee（本文正文与其逐字一致）
- 父会话纪律声明：仅通过 spawn_subagent 派遣与 subagent_result 读取真实终态；父代理未亲自执行审查、未用总结代替审查结论；未运行完整 R9、未运行任何测试、未签署任何授权、未调用 GLM 外部效能试验、未 push、未合 main、未重启或安装服务。本回执文件是本次派遣在隔离工作树内的唯一写入（untracked，未进 staged）。
- 落盘时间：2026-10-15T01:2x+08:00（以文件系统 mtime 为准）

---

审查完成，全部证据链闭合。以下为最终回执（供父代理原文落盘）。

---

# RULE-AI-28 代码闸独立审查回执 · rule-boundary-agency-20261014 staged 候选

## 1. Reviewer 身份自述

本会话由父代理 RULE-AI-28 经 spawn_subagent 创建，为**独立代码审查 Reviewer**：新会话、新上下文、未参与被审补丁的任何开发。工具约束：无网络访问；严格只读（未写/删/改任何文件、未落盘 /tmp、无 git 写操作、未运行 pytest/测试/构建/被审代码、未运行完整 R9）；仅执行 ls/cat/grep/sed/wc/shasum/git diff --cached(只读形态)/git show/git log/git status 类纯读取命令，以及一次不导入被审代码的 python3 字符串长度测量（stdin 解析 `git show` 输出）。本审查为**普通工作审查**，不构成 Rule31 一次性签署审批、Provider 放行或安装授权（锚 RULE-AI-28"审查是质量闸不是授权闸"）。审查前按纪律完成有界 method 检索（limit=5），采纳 `method:diff-partition-revision-rereview-ff8f3977837d` 与 `method:revision-recheck-diff-first-rerun-embedded-commands-5b0ed2568799` 的方法（hunk 集合=核对清单、逐 hunk 独立验证、删除/排除类声明用 grep 零命中验证）。

## 2. 身份核验（fail-closed，三项全过）

| 项 | 期望 | 实测 | 结果 |
|---|---|---|---|
| staged diff 字节数 | 16716 | `git diff --cached --no-ext-diff \| wc -c` → **16716** | ✅ |
| staged diff SHA-256 | c67cdf77…02c90 | `shasum -a 256` → **c67cdf7750417450ed979232842a3f2be274658d5f5e7de4cb42428698802c90** | ✅ |
| 文件清单 | 六文件 | `--name-only` 输出与期望**逐项一致**（六文件，无多无少） | ✅ |

补充：`git status --short` 显示六文件全部处于 staged（A/M×5），`git diff --stat`（unstaged）为**空** → 本审查中以 sed/grep 读取的工作树文件内容与 staged 内容一致，证据面无偏差。存在一个 untracked 文件 `docs/results/RESULT-20261014-glm53-reviewer-budget-offline-diagnosis.md`，不在 staged 审查面内，仅如实记录（其 gitignore 盲区风险属 push 闸职责）。

## 3. 必读上下文核验

AGENTS.md（33 行）、docs/DEVELOPMENT_REPAIR_SAFETY.md（396 行）、skills/code-review-gate/skill.md（35 行）均存在并全文读取；docs/ai_rules.md 中 RULE-AI-28（444-467）、RULE-AI-31（505-526）、RULE-AI-32（527-540）完整正文已读，另读入 541-567（《配置扩展》《配置生命周期约定》）支撑 B 维度。**无缺失文件。**

## 4. 逐 hunk 审查记录（共 8 个 hunk，无一跳过）

**Hunk 1/8** — `docs/results/RESULT-20261014-rule-boundary-agency-step1.md`（新文件，+34 行）：结果文档。声明与实测可交叉核验项全部吻合（见 F/H）；运态声明（3 failed→3 passed、77 passed、Ruff PASS 等）**本 Reviewer 无法独立复核**（禁止运行测试），标注为依赖执行方回执的未复核项。文档自身明确"不具有生产推广资格、独立 Reviewer/全量 R9/merge 未执行"——诚实边界正确。

**Hunk 2/8** — `registry_introspection.py:70`（@@ -67,7 +67,7）：full 版 search_records description 单行替换。对照 RULE-AI-31 第 1 条逐点核验（见 E）。**通过**。

**Hunk 3/8** — `rule_index.py:17`（@@ -14,6 +14,7）：新增 `_SECTION_HEADING_RE = re.compile(r"^##[ \t]+", re.MULTILINE)`。正则不匹配 `###`（H3，第三个字符非空白）与 `##X`（无空白），语义为"任意同级 H2"。**通过**。

**Hunk 4/8** — `rule_index.py:89-95`（@@ -87,7 +88,11）：`end` 从"下一个 RULE H2 或文件末尾"改为"下一个任意同级 H2"。逐点验证：RULE-AI-31 的 end 仍为 RULE-AI-32 的 H2 起点（ai_rules.md:527），与旧行为一致；RULE-AI-32 的 end 由 `len(text)`（吞掉 541 起四个非规则节）收敛为"## 配置扩展"（ai_rules.md:541）——这正是被修缺陷。**通过**。

**Hunk 5/8** — `registry.py:95`（@@ -92,7 +92,7）：compact 版 description 单行替换。**通过**（G 维度证据：本文件 diff 仅此一行，无任何逻辑/工具面变更）。

**Hunk 6/8** — `test_rule_presence_contract.py:248-287`（@@ -245,6 +245,46）：新增 `test_rule31_bounded_discovery_reaches_full_lazy_and_first_model_tool_packet`。用 stub（description/parameters 直接取 `_SEARCH_RECORDS_TOOL_DEF`）注册进真实 ToolRegistry，在 `lazy∈{False,True}` 两路径断言同一关键词集与 kind enum 超集，再经 `_mk`（tests/unit/test_err1210_recovery 复用）+ `_capture_tools` 检查 FakeLLM 首包。代表性成立：introspection 工具真实面由 `_SEARCH_RECORDS_TOOL_DEF` 直接聚合（corrections.py:171-189 `tool_defs()`），无第二份"真实工具 description"拷贝，无双真值漂移；`register` 同名覆盖仅告警不拒绝（registry.py:556-571）。**通过**（含一处弱断言，见 P2-2）。

**Hunk 7/8** — `test_rule_retrieval_contract.py:1-12`（imports）：新增 `re`、`RuleIndex` 导入，均为新测试实际使用。**通过**。

**Hunk 8/8** — `test_rule_retrieval_contract.py:80-124`（@@ -75,6 +77,50）：两个新回归。`test_last_rule_hydration_stops_at_non_rule_h2_without_losing_nested_content`（synthetic：RULE_DOC 尾规则后接 `### 适用示例` + 两个非规则 H2，断言 H3 保留、非规则 H2 排除、`source_version_token` 仍为全文 SHA、规则总数 3 不变）；`test_real_rules_sot_last_rule_and_model_receipt_exclude_configuration_sections`（真实 `docs/ai_rules.md`，`refs[-1]` 即 RULE-AI-32，断言水合内容与 `run_search_records` 回执均不含"## 配置扩展"/"## 配置生命周期约定"）。**通过**（含一处弱断言，见 P2-2）。

### A-H 维度结论

- **A（31/32 H2 边界）✅**：ai_rules.md 不在六文件中，文档零侵入零重排；代码侧修复使 32 的边界收敛到 541 行（实读 H2 映射：527 RULE-AI-32 → 541 配置扩展），31/32 正文均完整、无截断、无错插。旧新逻辑对非末位规则（31）行为等价（`matches[index+1].start()` ≡ 下一 H2 起点）。
- **B（配置扩展污染）✅**：变更**消除**既有污染（旧行为 RULE-AI-32 水合吞入《配置扩展》《配置生命周期约定》《R8.24-A》《卡片生命周期治理指针》四节）；无任何新文本插入该节；双测试（synthetic + 真实 SoT + 回执）反向断言排除。
- **C（H3 保留）✅**：`_SECTION_HEADING_RE` 不匹配 `###`；代码注释明示 "Nested ### headings remain part of the Rule's exact source text"（rule_index.py:91-93）；测试断言 `"### 适用示例" in row["content"]`。如实说明：当前真实 SoT 的 31/32 节内无 H3 子标题（505-540 通读），真实路径 H3 保留由 synthetic fixture 覆盖。无删除/合并/降级。
- **D（Full/Lazy 一致性）✅**：两条源头（registry_introspection.py:70 full / registry.py:95 compact）同步更新；`parameters` 两路径均未动，lazy skeleton 由同一 parameters 派生并保 type/enum/properties/items/required（registry.py:706-745 实读），kind enum 含 method/experience/lesson/rule（registry_introspection.py:81-104 实读）；compact 为 full 的无损压缩（豁免与自主判断语义未反转，full 独有"零命中不反复换词"属压缩省略）；新测试在两路径断言同一关键词集——恰好补上 description 双份手工维护的漂移回归。未发现 schema 漂移。
- **E（Rule31 边界）✅**：新描述与 RULE-AI-31 第 1 条逐点对齐（实质多步/工具任务、≤2 类、每类≤5、一次检索、同窗口不重复、简单问答/闲聊/纯复述豁免、零命中不反复换词）；反向抑制检查通过——保留"历史适用性由模型判断，不由程序自动采用""非每轮强制、不强制顺序"（既有锚点测试 test_search_records_contract_carries_timing_semantics:240-245 所断言的关键词在两个新字符串中均在，静态可核）；diff 为纯字符串，无任何程序门控新增，未把发现变成机械强制。
- **F（首包成本）✅ 实测量化**：full 572→564 字符（−8）、compact 430→416 字符（−14），实测与 RESULT 表格"430→416"吻合；预算锚 `_BASELINE_SEARCH_RECORDS_COMPACT=390`（test_rule_presence_contract.py:29）+ 容差断言 `len(compact)−390≤80`（:216-217）→ 416−390=26≤80 通过；rule_index.py 净 +5 行为索引构建代码，不进 prompt。首包成本**减少**。RESULT 未列 full 口径（572→564），见 P2-3。
- **G（工具权限未收缩）✅**：registry.py diff 仅一行字符串；schemas()/register()/allowlist/参数零变更；无工具移除、收紧或降级。
- **H（RULE-AI-32 ledger 红）✅ 不属本补丁责任**：红因实证——RULE-AI-32 由 HEAD 之前提交 `7121bca9a` 写入 ai_rules.md:527（`git log --oneline -3 -- docs/ai_rules.md`），私有 ledger 存在（.codeartsdoer/specs/rule_presence/rule-presence-ledger.md，18003B，43 处 RULE-AI- 提及）但 `grep "RULE-AI-3[12]"` 仅命中 31 的补登行（:15），32 未登记 → `test_ledger_covers_all_sot_rules`（:323，skipif 不生效因文件存在）红。本补丁未触碰该测试（唯一 hunk 在 :245 区插入）、未改 ai_rules.md、未改 ledger、未抬基线（390 未动）；RESULT 如实披露并以命令行 deselect 隔离（未在测试文件内加 skip，非 baseline widening）。该红的"fix 或 explicit acceptance"闭环（AGENTS.md known-reds 纪律）仍悬置，RESULT 已声明归属后续 R9 阶段——记录为流程债（P2-4），不阻断本候选。

## 5. 问题清单

- **P0（阻断）：无**
- **P1（应修）：无**
- **P2（建议）4 条**：
  1. `rule_index.py:17/94` `_SECTION_HEADING_RE` 不感知 fenced code block——规则正文内行首 `## `（如代码块内 shell 注释）会被误判为节边界提前截断。当前 ai_rules.md 的 36 个 `^## ` 匹配经核对全为真实节标题，且旧行为（`_RULE_HEADING_RE`）有同构限制、RESULT 已如实声明适用边界，故仅建议：后续加一个 fenced-code 反例 fixture 或维持现状并保留声明。
  2. `test_rule_retrieval_contract.py:109` `assert "RULE-AI-31" in refs and refs[-1]` 中 `refs[-1]` 为恒真断言（非空列表末元素必真），建议改为有信息量的断言（如 `refs[-1] == "RULE-AI-32"` 或 startswith 校验）。
  3. RESULT 表格只报 compact 预算口径（430→416），建议补 full 口径（572→564）一句，完整量化首包影响。
  4. 存量 ledger 红的治理闭环（补登 32 或登记 explicit acceptance）悬置，须按 RESULT"交接门槛"在后续 R9 独立阶段兑现，勿遗忘。

## 6. 最终 verdict

**PASS**（附 4 条 P2 记录；P0/P1 均无）。按 RULE-AI-28 语义：PASS 是进入下一阶段（全量测试）的必要条件，不替代任何授权通道、不构成签署/放行/安装授权。以下声明**不在本回执覆盖范围**：全量 R9 未执行、测试运态结论未独立复核（依赖执行方回执 + 后续全量测试）、真实外部 Provider 物理送达未验证（FakeLLM 首包观察≠真实模型阅读证明，RESULT 自身已如实区分）。

## 7. 建议采纳/拒绝清单（对补丁本身）

- **采纳**：① Rule 末端边界改为"下一任意同级 H2"、H3 保留、SoT 全文 SHA 不变的 exact hydration 修复（hunk 3/4）；② full/compact 双描述同步对齐 RULE-AI-31 现行文（hunk 2/5）；③ 双层回归（synthetic 边界 + 真实 SoT + run_search_records 回执 + FakeLLM 首包 full/lazy 双路径）（hunk 6/8）；④ 诚实的 RESULT 文档（基线 SHA、未验证项、存量红归属均如实）。
- **拒绝：无**。P2 四条均为改进建议，采纳与否由执行方答复时说明。

## 8. 实际执行的命令与读取文件（证据可复核）

**命令**（全部只读，workdir=WT）：`git diff --cached --no-ext-diff | wc -c` / `| shasum -a 256`；`git diff --cached --name-only`；`git diff --cached --no-ext-diff`（全文，因截断改按文件分取）；`git diff --cached --no-ext-diff -- <六文件各一>`；`git status --short` + `git diff --stat`；`git log --oneline -3 -- docs/ai_rules.md` + `git log --oneline -2`；`git show <HEAD:/:path>`（4 次，供长度测量）；grep/sed 定位：ai_rules.md H2 映射与 444-467/505-567 段、registry.py 700-760/815-845 与 register:556-571、registry_introspection.py 60-150、rule_index.py 75-135、test 两文件多段（200-258/316-360/14-45/18-35）、corrections.py 150-205、ledger grep；python3 -c 长度测量×4（stdin 解析，未导入被审代码、未落盘）；search_records method 检索（limit=5）。注：`evidence://v1/d5e4…` 恢复引用因本会话无 read_evidence 工具不可读，已改用按文件 diff 获取同一内容，不影响覆盖完整性。

**读取文件**：AGENTS.md、docs/DEVELOPMENT_REPAIR_SAFETY.md、docs/ai_rules.md（节选）、skills/code-review-gate/skill.md、六 staged 文件的 diff 与工作树正文、src/llm_loop/introspection/corrections.py（节选）、.codeartsdoer/specs/rule_presence/rule-presence-ledger.md（grep 节选）。

**未复核项（诚实标注）**：所有测试通过数、Ruff/py_compile、补丁前 RED 复现——本 Reviewer 被禁止运行测试，以上均以静态证据交叉核验其**可核验部分**（预算算术、锚点词、H2 映射、文件时序），运态结论信任执行方回执并留待全量 R9 独立裁决。
