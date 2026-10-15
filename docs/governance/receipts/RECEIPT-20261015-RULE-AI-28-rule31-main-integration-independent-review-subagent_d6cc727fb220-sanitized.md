# Sanitized independent Reviewer receipt (derived evidence)

> This is a security-filtered derivative of the original Reviewer receipt, NOT the original immutable EventStore response.
> child_id: `subagent_d6cc727fb220`; original raw receipt SHA-256: `b0c7ecf992880f21e47ccac84ecbe9eced56a2ab94a98b4dedd6657c2d6fd97c`.
> Only 2 local user-home path prefix(es) were replaced by `<LOCAL_USER_HOME>/`; all substantive review findings, candidate fingerprints, and verdicts remain unchanged.
> Original raw content remains unmodified in its local source file and in the corresponding independent child EventStore.

---

# RECEIPT — RULE-AI-28 独立只读代码审查回执（Rule31 main 精确集成候选）

- 回执类型：独立 Reviewer 终态报告原样落盘（父会话仅编排与落盘，未参与审查）
- child_id：`subagent_d6cc727fb220`（spawn_subagent；inherit=false 全新会话，未参与候选编写；model `glm/glm-5.3`；depth=0）
- child 终态：child_state=completed，child_outcome=completed；rounds=26；tools=42；tokens_in=1,040,481；tokens_out=30,145（subagent_result 回执，acquired_at 2026-10-15T07:34:05+08:00）
- 工具约束（运行时 E4 强制白名单）：read_file / inspect_code / execute_command；network=false；child 自述全程零写入、未运行任何测试/构建/被审代码/脚本、无网络外发、未 kill 任何进程
- 审查对象：worktree `<LOCAL_USER_HOME>/Project/llm-first-loop-mirror/.worktrees/rule31-main-integration-20261015`；分支 `fix/rule31-main-integration-20261015`；基线 main=`2ad0bc06d55aefa3496bdf8c26bad1a4dc2963b2`
- 候选冻结面（child 第零步独立复核 0a-0f 全 PASS）：7 个 staged 文件；`git diff --cached --no-ext-diff` = 20,888 字节；SHA-256 `a26be24d3631473ad9b6792ac95f96f63f7c98218cd65443d3300f0fc4f2b811`
- child 总裁决：**PASS**（P0=0，P1=0，P2x3：见报告 C 节）
- 终态原文完整性：subagent_result 回执 result_truncated=true；父会话经 recovery_ref `evidence://v1/cdfac64bbad3a5af31f53a78db612f06158ea5c8eba0f3280847c5c0cb890035` 分页恢复全部 12,156 字符（complete=true；blob_sha256 `052c8781ba02031011316cc0c26ea208313d09a2223f456d5cb491bed07dce6e`）后逐字落盘
- 边界声明：本回执仅为 RULE-AI-28 质量闸审查结论，不构成合并 main、push、部署、服务重启、真实 Provider 效能测试或任何签署/预算授权；完整 R9 未由本 child 执行（见报告 D 节"未经证实项"）
- 父端落盘纪律：仅新建本文件，未覆盖/修改任何既有文件；落盘后复核 staged 面仍为 20,888 字节 / SHA `a26be24d...f2b811` / 7 文件不变，本文件 untracked 未入 index；child 结束后工作树除本回执外无任何新增改动（status 复核）
- 落盘时间（父会话本地）：2026-10-15 07:35 前后（+08:00）

---

## 以下为 child `subagent_d6cc727fb220` 终态报告原文（verbatim，未删改）

全部审查步骤完成。以下为终态报告。

---

# RULE-AI-28 独立只读审查报告（Rule31 main 精确集成候选）

**审查对象**：worktree `<LOCAL_USER_HOME>/Project/llm-first-loop-mirror/.worktrees/rule31-main-integration-20261015`，分支 `fix/rule31-main-integration-20261015`，基线 main=`2ad0bc06`
**审查人身份**：独立只读 Reviewer（全新会话，未参与候选编写；不修复、只报告）

## A. 身份核对（第零步）

| 项 | 要求 | 实测 | 结论 |
|---|---|---|---|
| 0a | 分支名 | `fix/rule31-main-integration-20261015` | **PASS** |
| 0b | HEAD | `2ad0bc06d55aefa3496bdf8c26bad1a4dc2963b2`（恰在基线，改动全在 index） | **PASS** |
| 0c | staged 恰好 7 文件 | `.codeartsdoer/specs/rule_presence/rule-presence-ledger.md`、`src/llm_loop/introspection/registry_introspection.py`、`src/llm_loop/introspection/rule_index.py`、`src/llm_loop/tools/registry.py`、`tests/unit/test_browser_attestation_v01.py`、`tests/unit/test_rule_presence_contract.py`、`tests/unit/test_rule_retrieval_contract.py` | **PASS** |
| 0d | diff 字节数 | `20888` | **PASS** |
| 0e | diff SHA-256 | `a26be24d3631473ad9b6792ac95f96f63f7c98218cd65443d3300f0fc4f2b811` | **PASS** |
| 0f | 无未暂存/未跟踪 | `status --short` 仅 7 行 `M ` 开头；`^??` 计数 0 | **PASS** |

身份核对六项全部通过，未触发 BLOCK。

## B. 逐 hunk 审查发现

### 1) `src/llm_loop/introspection/rule_index.py`（1 hunk，+4/-1）

- **SoT 边界事实核对**：真实 SoT 中 Rule33 H2 位于 `docs/ai_rules.md:541`，其后紧邻的第一个 H2 是非 Rule 的 `## 配置扩展`（:558），随后 `## 配置生命周期约定`（:568）、`## R8.24-A 迁移去向指针`（:585）、`## 卡片生命周期治理指针`（:615）。与委派描述一致。
- **水合不跨章**：`rule_index.py:93-94` 新逻辑 `_SECTION_HEADING_RE.search(text, match.end())`（`^##[ \t]+`，MULTILINE）从当前 rule 标题行尾起找下一个任意 H2，`end=next_section.start()`。Rule33 水合体到 `## 配置扩展` 行首即止。已检查，未见问题。
- **合成 Rule 末条同样不跨章**：同一循环代码覆盖合成文档；新测试 `test_last_rule_hydration_stops_at_non_rule_h2_without_losing_nested_content` 用 fixture（RULE-AI-22 为末位 + 两个配置 H2）断言 `"## 配置扩展" not in content`、`"## 配置生命周期" not in content`。已检查，未见问题。
- **嵌套 H3 完整保留**：`^##[ \t]+` 要求 `##` 后紧跟空格/tab，`### xxx` 第三字符为 `#` 不匹配；fixture 断言 `"### 适用示例" in row["content"]` 且 `"细节仍属于 RULE-AI-22" in row["content"]`。当前 SoT 实无 H3（`grep -c '^### '`=0），该保障由合成 fixture 承载。已检查，未见问题。
- **不扩大规则数量、不自制语义选择**：entries 仍只由既有 `_RULE_HEADING_RE` 产生（本次未改）；新测试 `len(...)==3` 锁定合成文档卡片数、真实 SoT 测试 `len(refs)==len(set(refs))` 锁定无重复；改动纯机械（章节边界），无相关性/重要性判断。已检查，未见问题。
- **行为影响面**：对非末位 rule，main 中下一个 H2 就是下一个 rule 标题，新旧 end 计算结果相同；唯一行为变化是末位 rule（当前 Rule33）不再吞入四个非 rule 配置章节（main 旧行为会把这些运维章节当作 Rule33 正文水合且 `projection_complete=True`——本次是修复，非回退）。
- **fenced code block 残余风险（实测定级）**：`grep -c '^```' docs/ai_rules.md` = **0**——当前 SoT 不存在任何 fenced code block，伪 H2 误触风险**当前事实为零**。残余风险（未来在 fenced 内出现 `## xxx` 行会导致该 rule 提前截断且 `projection_complete=True` 的静默截断）登记为 **P2**；另注意 `_RULE_HEADING_RE` 把 fenced 内 `## xx（RULE-AI-99）` 误建为假卡属 main 既有逻辑，非本次引入。
- **P2-1**（信息级）：`rule_index.py:16` 的 `_RULE_HEADING_RE` 用 `^##\s+`（`\s` 可匹配换行、跨行成题），而 `:17` 新增 `_SECTION_HEADING_RE` 用 `^##[ \t]+`（不跨行）。极端构造下（`##` 后直接换行、下一行含 ref）两正则识别面不一致；当前 SoT 无此形态，测试 regex（`^## [^\n]*?(RULE-AI-\d+)`）与实现同样存在此细微差异。建议后续统一口径。

### 2) `registry_introspection.py`（Full）与 `registry.py`（Compact），各 1 hunk

- **Rule31 开局提示七要素逐项核对**（Full `registry_introspection.py:70` / Compact `registry.py:95`）：
  - 最多两类：`从method/experience/lesson中选≤2类` / `选≤2类` ✓
  - 每类≤5：`每类≤5` ✓
  - 同一任务窗口仅一次：`同一任务窗口不重复` ✓
  - 轻任务豁免：Full `简单问答、闲聊、纯复述豁免` / Compact `简单问答豁免` ✓（Compact 精简，见 P2-3）
  - stable ref 精确水合：`只以搜索结果返回的完整 method:<id> stable ref 精确水合，不猜 method:<关键词>` / `仅以返回的method:<id> stable ref 精确水合，不猜 ref` ✓
  - 模型自主判断：`命中后来源时效与任务适用性由模型判断，不由程序自动采用` / `历史适用性由模型判断` ✓；且均为 description 提示，无程序强制路径（search_records 执行逻辑未动）✓
- **main 既有内容未回退（grep 双向计数核对）**：`registry.py` 中 service_control generation/CAS/reaper 分档说明（:84）、`notify_external_result`（:882）、E2/E6 拒绝诊断（:1117-1189）、get_tool_schema/lazy Schema（:82、:2027+）全部在场，service_control/notify_external_result/expected_generation 计数 staged=main=1/1/1；`registry_introspection.py` 中这三者 main 与 staged 均为 0（main 本无，不存在回退）。kind enum 含 `method/experience/lesson/rule`（:76-98，实测枚举在场）。已检查，未见问题。
- **FakeLLM/first tool packet**：main 中这两个文件无 FakeLLM 相关内容（不适用"保留"检查）；本次在 `test_rule_presence_contract.py` 新增 first FakeLLM tool packet 断言（见下），属强化。
- **Compact 长度棘轮静态复算**（既有测试 `len(compact)-390<=80`）：新值整行 442 字符（`wc -m`，UTF-8 按字符计；对照 `wc -c`=830 字节可证字符口径正确），扣缩进/引号/逗号/换行后 value≈434，434-390=44≤80 ✓；main 旧值≈448，新值更短。
- **P2-2**（建议）：Full 版旧描述中 method discovery 域枚举含"写前校验""等高频域""或准备直接开始重试、修复、拼装多步流程时"触发语，新文案收窄为"失败重试/换源、编辑冲突、超时判定、浏览器定位、检索与验证纪律"。域枚举本为示例非穷尽、核心检索义务由新条款承接，无实质语义损失，但触发场景措辞较旧版略简，建议知悉。

### 3) `.codeartsdoer/specs/rule_presence/rule-presence-ledger.md`（2 hunks，+4/-2 -> 实际 stat 5 行变更）

- **仅新增正式 Rule31 行**：`ledger:112` 新增 `| RULE-AI-31 | ...`；main 基线 grep `^| RULE-AI-31 ` 计数 0（确认 main 漏登）。
- **Rule32/33 逐字保留（SHA 证据）**：main 与 staged 的 `^| RULE-AI-32 ` 行 SHA-256 均为 `f832425f5a1e...54344`，`^| RULE-AI-33 ` 行均为 `6b3522a868...a36c`——逐字节一致。
- **records=37 静态复算（不运行脚本）**：读 `scripts/rule_presence_audit.py` 源码（:35 `_RULE_RE=re.compile(r"RULE-AI-\d{2}")`，:239-243 对 SoT 全文 findall+set 去重，:276-283 追加 `_EXTRA_SCOPES` 3 条）。静态复算：SoT 全文去重 ref = **34**（RULE-AI-00~33 全连续编号，其中 RULE-AI-21 仅出现在 :333 编号空缺说明文字、无 H2 正文）+ 3 = **37** ✓，与 header `records` 行及"正式 Rule 条款 34 + 附则/子规则/方法层 3"声明吻合。新测试还把 header 数字与 `audit.inventory()` 运行值挂钩（我未运行，见 D）。
- **伪 PASS 结构已修复而非引入**：旧断言 `ref not in ledger` 允许 header 叙述提及即可通过（这正是 main 上 Rule31"header/records 行提及却无正式行"的形态）；新断言 `re.findall(r"^\| (RULE-AI-\d{2}) \|", ledger)` 只认正式表格行 + 无重复 + 每个正式 ref 有行。我另行静态复算 rows 集合：§2.1（03/11/20）+ §2.2（18/22/24）+ §2.3（00,01,02,04-10,12-17,19,23,25-33 共 27 行）= 33 个唯一行，与 `_sot_rule_refs`（H2 口径 33 个，21 不在内）完全闭合，`missing==[]` 成立；§2.4 附则行（`RULE-AI-00 附则①~⑥` 等）不被 rows regex 误捕。
- **门禁断言未削弱**：`test_ledger_covers_all_sot_rules` 仅加强；diff 无任何断言删除/跳过/skipif 新增（既有 skipif `_LEDGER_AVAILABLE` 为 main 原有）。
- **P2-3**（建议）：§5 回归台账未按历史惯例（:160-162 每轮盘点均登记）追加 2026-10-15 本轮盘点行（header 已记事实，仅文档完整性）；另 header 措辞"正式 Rule 条款 34"易误读——按 audit 口径 34 是"SoT 全文去重 ref 数（含无正文的 RULE-AI-21 引用）"，正式 H2 条款为 33，数值正确但表述可再精确。

### 4) 三个定向测试

- **`test_rule_retrieval_contract.py`**（+49）：真实 SoT 测试动态断言 `refs[-1]`（:112，当前=RULE-AI-33，未来新增 Rule34 后自动前移，且 `{"31","32","33"} ⊆ refs` 防倒退；refs 为空时子集断言先失败，fail-closed）。source hash 口径与实现完全一致（双方均 `read_text(encoding="utf-8")` 后 `sha256(text.encode())`，:106/:114 对 `rule_index.py:78/:83`）。既有 9 个测试零改动（含 `len(prompt)<1200` universal prompt 预算断言、`"RULE-AI" not in prompt`）。已检查，未见问题。
- **`test_rule_presence_contract.py`**（+49/-2）：新增 `test_rule31_bounded_discovery_reaches_full_lazy_and_first_model_tool_packet`——SearchRecordsStub 直接复用 `_SEARCH_RECORDS_TOOL_DEF` 真实 description/parameters（非自制文案）；`schemas(lazy=False/True)` 双面断言关键词 `("method","experience","lesson","≤2类","每类≤5","同一任务窗口","简单")` 与 enum；用既有 `_mk`/`_capture_tools` helper（tests/unit/test_err1210_recovery 导入为 main 既有）捕获**真实 FakeLLM 首个 tool packet** 中 search_records 的描述与 enum——断言真实 wire 形态而非 mock 返回值。`test_ledger_covers_all_sot_rules` 加强如上。已检查，未见问题。
- **`test_browser_attestation_v01.py`**（+8/-6）：`bind(("127.0.0.1", 0))` 取内核临时端口且**不 listen**（socket 在 with 块内持有，端口不被抢占）；`attest_port` 真实执行（实现链 `attestation.py:252` -> `_listen_pids:143` 用 `lsof -nP -t -iTCP:{port} -sTCP:LISTEN`，无任何 mock）；bind-only socket 无 LISTEN 状态不命中 lsof 过滤 -> `无监听 PID ... fail-closed real` -> 断言 `verdict=="real"`、`"无监听" in detail` 语义自洽。**fail-closed 验证**：lsof 环境异常时 detail 为"lsof 调用失败…"不含"无监听" -> 断言失败（红），不假通过。**无 kill**（grep 全文件仅注释行含"mock"字样，无 kill/Path 残留，`Path` import 删除安全）。固定端口 39099 的环境耦合（被真实应用占用即误红）被消除——改进。已检查，未见问题。

### 5) 全局面

- **语义侧效应**：`docs/ai_rules.md` 未改动（SHA-256 与 main 逐字节一致 `92d48923...a8c`）；`prompt.py` 未动（`_BASE_PROMPT` hash 既有测试守卫）；检索评分/空 query 卡片/fallback/多 ref 不隐式选择逻辑全部未变。代码+文档+测试三类改动语义方向一致（机械边界修复 + 提示条款 + 守卫加强），无混入无关机制（RULE-AI-32 hunk 级纪律符合：stat 显示各文件均为最小 hunk）。
- **信息泄露**：staged diff 敏感模式扫描（password/secret/api_key/jwt/bearer/ssh/sk- 等）两轮均无命中；无新增绝对路径/密钥/token/端点（测试内 `/nonexistent/...` 假路径、`/tmp/attest-outside-profile` 为 main 既有）。
- **反例检验（纯推理+只读核对，未执行代码）**：1. 未来 SoT 在末位 rule 后写入无空格伪 H2（`##Release`）不被识别 -> 末位 rule 吞尾，但真实 SoT 测试的 `"## 配置扩展" not in content` 断言可捕获大多数此类漂移（伪 H2 出现在配置扩展之前时）——残余，P2 级；2. fenced 内伪 H2：当前 SoT 零 fence，风险为零，未来风险已登记 P2-1 关联；3. bind 端口竞态：with 持有期内其他进程无法 LISTEN 同端口，lsof 只查 LISTEN，无竞态窗口；4. `refs` 为空：子集断言先红；5. `_SECTION_HEADING_RE` 从 `match.end()` 起搜不会回吞当前标题行。未发现可构造的 P0/P1 级反例。

## C. 总裁决

**PASS**（P0=0，P1=0；P2 建议项 3 条不阻断）
- P2-1：`rule_index.py:16-17` 两个 heading 正则的 `\s` 跨行 vs `[ \t]` 口径差异 + fenced 伪标题残余风险（当前 SoT 无 fence，事实为零）——建议后续统一或加 fixture。
- P2-2：Full 版 method discovery 域枚举措辞较 main 收窄（去"写前校验"等示例词）；Compact 豁免仅"简单问答"（Full 完整）。
- P2-3：ledger §5 未按惯例登记本轮盘点行；"正式 Rule 条款 34"措辞宜注明含 :333 的 RULE-AI-21 引用（audit 口径）。

## D. 未经证实项（依赖执行方声明，未独立复核）

1. RED3 -> GREEN 61/61、`scripts/ci_gate.sh --quick` 退出 0（319 tier0/Pyright/Ruff/Env/WebUI）、7 文件 staged 安全扫描——我受禁令约束未运行任何测试/构建/脚本，仅做静态代码审查。
2. `audit.inventory()` 运行态实际输出（含 `_load_base_prompt` 在 pytest 环境的 import）——我以源码口径静态复算 34+3=37，未运行脚本验证。
3. `registry.schemas(lazy=True)` 与 FakeLLM `engine.run` 的运行时 wire 形态——仅静态审阅实现（`registry.py:706-708` docstring）与测试代码推断。
4. 本审查纪律要求的开局 `search_records(kind=method)` 有界检索无法执行：本会话工具集（read_file/inspect_code/execute_command）不含该方法检索工具，已如实记录；同理我无法在收口时落 `record_use` 记账，此报告本身即回执载体。

## E. 命令清单（实际执行的全部只读命令）

```
git --no-pager -C <W> branch --show-current
git --no-pager -C <W> rev-parse HEAD
git --no-pager -C <W> diff --cached --no-ext-diff --name-only
git --no-pager -C <W> diff --cached --no-ext-diff | wc -c
git --no-pager -C <W> diff --cached --no-ext-diff | shasum -a 256
git --no-pager -C <W> status --short
wc -l AGENTS.md docs/DEVELOPMENT_REPAIR_SAFETY.md docs/ai_rules.md
grep -n "^## \|^### " docs/ai_rules.md | head -80
git --no-pager -C <W> diff --cached --no-ext-diff          （整体，输出截断后改逐文件）
git --no-pager -C <W> diff --cached --no-ext-diff -- src/llm_loop/introspection/rule_index.py
git --no-pager -C <W> show 2ad0bc06:src/llm_loop/introspection/rule_index.py | sed -n '1,140p'
grep -c '^```' docs/ai_rules.md ; grep -c '^### ' docs/ai_rules.md ; grep -n '^# ' docs/ai_rules.md ; grep -n '^```' docs/ai_rules.md
git --no-pager -C <W> diff --cached --no-ext-diff -- .codeartsdoer/specs/rule_presence/rule-presence-ledger.md
grep -o 'RULE-AI-[0-9][0-9]' docs/ai_rules.md | sort -u | awk '{print NR": "$0}' ; ... | wc -l
shasum -a 256 docs/ai_rules.md ; git --no-pager show 2ad0bc06:docs/ai_rules.md | shasum -a 256
git --no-pager -C <W> diff --cached --no-ext-diff -- src/llm_loop/introspection/registry_introspection.py
git --no-pager -C <W> diff --cached --no-ext-diff -- src/llm_loop/tools/registry.py
grep -n 'service_control|notify_external_result|expected_generation|E2|E6|FakeLLM|char-budget|Schema' <两文件>（staged 与 main 各一轮，grep -c 计数）
git --no-pager -C <W> diff --cached --no-ext-diff -- tests/unit/test_rule_retrieval_contract.py
git --no-pager -C <W> diff --cached --no-ext-diff -- tests/unit/test_rule_presence_contract.py tests/unit/test_browser_attestation_v01.py
grep -n 'def attest_port' -A 40 src/llm_loop/browser/attestation.py
grep -n '_listen_pids' -A 20 src/llm_loop/browser/attestation.py ; grep -n '"enum"' -B3 -A6 src/llm_loop/introspection/registry_introspection.py
sed -n '73,137p' src/llm_loop/introspection/registry_introspection.py
grep -n 'Path|kill|mock|Mock' tests/unit/test_browser_attestation_v01.py ; sed -n '10,35p' tests/unit/test_browser_attestation_v01.py
git --no-pager show 2ad0bc06:...ledger.md | grep '^| RULE-AI-32 ' | shasum -a 256（及 33、及 grep -c '^| RULE-AI-31 '，对 staged 同构执行）
grep -n '"search_records": "' src/llm_loop/tools/registry.py ; sed -n '95p' src/llm_loop/tools/registry.py | wc -m / wc -c ; git --no-pager show 2ad0bc06:src/llm_loop/tools/registry.py | sed -n '95p' | wc -m
git --no-pager diff --cached --no-ext-diff | grep -inE '<敏感模式>' （两轮）
git --no-pager diff --cached --no-ext-diff --stat ; git --no-pager status --porcelain | grep -c '^??'
（附注：两条命令曾因 /bin/sh 不支持进程替换语法失败退出码 2，未产生任何副作用，已改写重跑获得上述结果）
```

**审计声明**：以上全部为只读命令（git 只读子命令均带 --no-pager；无任何写/网络/测试/构建/被审代码执行）。裁决依据仅为静态证据与双份 SHA/计数复算，未采用执行方声明替代检查。
