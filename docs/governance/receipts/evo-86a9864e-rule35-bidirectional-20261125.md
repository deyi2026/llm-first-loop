# EVO-20261125-86a9864e · RULE-AI-35 双向实测回执

- 演进：EVO-20261125-86a9864e（人工 2026-11-25 18:35 批准，`human_exec_override=true`，executor=ai）
- 范围：RULE-AI-28 Host 准入动作分类的两处误拦/误分类
- Goal / lane：GOAL-20261125-40677ea1 / lane-27aa2dc0（分支 `fix/rule28-heredoc-data-region-classify-20261125`，base main=`1f0601e9d0225bfb66160e9fb2a569eba176cf99`）
- **证据层级：本地实测**（直接调用分类器函数；单元测试另经 `HostReviewAdmission.check_shell` 走拒绝路径）。**不是「真实入口已生效」**：本会话运行在 gen 456（`6349346d8a93`）的已部署运行时上，其分类器仍是旧版；经 `execute_command` 真实入口的活体验证须在含本修复的 main 部署之后进行（TASK-40677ea1-004）。

## 1. 实测现象与根因（与建议正文的差异）

| 现象 | 建议正文的归因 | 实测根因 |
|---|---|---|
| ① 2026-11-25 17:11：`cat > /tmp/x.md <<'PREOF' … PREOF` 被拒「不存在覆盖当前产物、目标及父会话的有效独立审查资格」 | heredoc 数据区参与了动作分类 | 数据区已被段网与内容网豁免（EVO-20261102-99717443）。漏的是第三张网：`classify_host_shell` 的反引号网 `_active_backtick_substitutions(value)` 始终扫原始全文，把正文里的 Markdown 代码span（一对反引号）当成命令替换，其中的 `git push` 字样使整条命令归为 `git_push` |
| ② 2026-11-25 16:05：`… ; python3 -m pytest --version; …` 的观测行为「动作=全量 pytest（full_test）」 | 非执行形态未识别 | 观测行来自 `review_gate.classify_review_gate_command`（纯正则），只认 `-k`、`::`、`.py`、`tests/` 收窄，不认 `--version` 等旗标 |

17:11 被拦命令的原文没有逐字留存（动作轨迹只存前 300 字符）。重建依据：改写后通过的 PR 描述文件 `/tmp/lfl_evo_dd29a9e1_pr_body.md`，以及 main 源码上的受控对照——同一正文，裸文本 `git push origin main` 得 `None`，加一对反引号得 `git_push`。

## 2. 修法

- `review_host_admission._strip_heredoc_units` 新增可选 `net_out` 镜像，收集 shell 实际解析的文本。仅当「终止符已配对 + 已豁免 + 引导位于 shell 顶层 + opener 行整行收在顶层」时数据体不进镜像，其余照常进（末项为 2026-11-26 接力修复，见 §8.2）。
- `_advance_quote_state`：逐字符推进引号状态，用于判定 `<<` 是否位于顶层（不在跨行未闭合的引号串内），以及 opener 行尾是否留下未闭合引号。
- `classify_host_shell` 的反引号网改扫 `"".join(net_parts) or value`。
- `review_gate.classify_review_gate_command`：逐个 pytest 调用取其所在命令段核对非执行旗标，全部为非执行形态、且命中之外不残留 pytest 词元才返回 `None`（后半句为 2026-11-26 接力修复，见 §8.1）。

### 与建议正文的偏离（RULE-AI-06 子规则 6：accepted 不冻结实现手段，新证据优先）

1. **豁免条件未放宽到无引号终止符。** 建议写「终止符配对成功时正文不计入」，但 `<<EOF` 的正文在 bash 中会做参数/命令替换，反引号真的会执行（实测 B3）。保留「带引号终止符 + 白名单数据接收者 + opener 行安全」的既有口径，只把剩余网的扫描面与之对齐。
2. **附加「引导位于顶层」条件。** 不加会引入新的漏放：`echo "start` 换行后接 `<<'EOF'`，在 bash 里 `<<` 落在双引号串内、不是 here-doc，体内反引号会执行（实测 B7）。这个形态今天是靠「扫原始全文」碰巧拦住的，无条件脱敏会放开它。
3. **词法失败兜底保持扫原始全文。** 骨架 shlex 失败时，逐行 heredoc 识别不可信（实测 B6）。
4. **同批闭合一处现存漏放（B9）。** 豁免体内的撇号使原始全文扫描的引号状态失步，其后骨架里的真实反引号替换被当成单引号内文本而漏判；脱敏后状态不再失步。这是同一张网的同一处改动，不是范围外的追加。
5. **未把顶层条件并入内容网的豁免判定（`is_exempt`）。** 并入会把「注释里的撇号 + 其后的 heredoc」误拦成新的假阳性，超出本次范围。

## 3. 探针与两侧输出

探针原文：同目录 `evo-86a9864e-probe-20261125.py.txt`，sha256 `d4650f04ca27cf35f9a596057eb403cea887ad040548f30479a2fa25318ac655`（101 行）。探针用 `chr(96)` 构造反引号：已部署的旧闸会拦下含字面反引号 `git push` 的写文件命令。

复现（`$REPO` 为仓库根；`.venv/bin/python` 为 3.13 解释器）：

    # 基线：origin/main 的 src 原样导出
    mkdir -p /tmp/lfl_evo_86a9864e_base
    git -C $REPO archive origin/main src | tar -x -C /tmp/lfl_evo_86a9864e_base
    $REPO/.venv/bin/python /tmp/lfl_evo_86a9864e_probe.py /tmp/lfl_evo_86a9864e_base/src

    # 被测：lane 工作树
    $REPO/.venv/bin/python /tmp/lfl_evo_86a9864e_probe.py .worktrees/evo-rule28-heredoc-data-region-20261125/src

### 基线（origin/main `1f0601e9d`）—— 退出码 1

    module = /tmp/lfl_evo_86a9864e_base/src/llm_loop/__init__.py
    == classify_host_shell ==
    MISMATCH  A1_md_code_span_in_exempt_body | expected=None actual='git_push'
    MISMATCH  A2_md_bullet_nohup_push | expected=None actual='git_push'
    MISMATCH  A4_pytest_literal_in_exempt_body | expected=None actual='full_test'
    MISMATCH  B9_apostrophe_desync_then_real_backtick | expected='git_push' actual=None
    KNOWN_GAP B11_real_push_on_opener_line | expected='git_push' actual=None
    == classify_review_gate_command ==
    MISMATCH  C01_pytest_version_python_m | expected=None actual='full_test'
    MISMATCH  C02_pytest_version | expected=None actual='full_test'
    MISMATCH  C03_pytest_capital_v | expected=None actual='full_test'
    MISMATCH  C04_pytest_co | expected=None actual='full_test'
    MISMATCH  C05_pytest_collect_only | expected=None actual='full_test'
    MISMATCH  C06_pytest_h | expected=None actual='full_test'
    MISMATCH  C07_pytest_help | expected=None actual='full_test'
    MISMATCH  C08_observed_1605_chain | expected=None actual='full_test'
    mismatches = 12 known_gaps_open = 1 of 33

（基线输出里其余 21 行为 OK，此处省略；被测侧完整输出见下。）

### 被测（lane 工作树，含本修复）—— 退出码 0

    module = …/.worktrees/evo-rule28-heredoc-data-region-20261125/src/llm_loop/__init__.py
    == classify_host_shell ==
    OK        A1_md_code_span_in_exempt_body | expected=None actual=None
    OK        A2_md_bullet_nohup_push | expected=None actual=None
    OK        A3_apostrophe_then_code_span | expected=None actual=None
    OK        A4_pytest_literal_in_exempt_body | expected=None actual=None
    OK        B1_real_push | expected='git_push' actual='git_push'
    OK        B2_real_backtick_substitution | expected='git_push' actual='git_push'
    OK        B3_unquoted_delimiter_body_expands | expected='git_push' actual='git_push'
    OK        B4_non_sink_receiver | expected='git_push' actual='git_push'
    OK        B5_real_push_after_exempt_body | expected='git_push' actual='git_push'
    OK        B6_opener_inside_open_string_lex_fallback | expected='git_push' actual='git_push'
    OK        B7_opener_inside_multiline_string_balanced | expected='git_push' actual='git_push'
    OK        B8_unterminated_body_kept | expected='git_push' actual='git_push'
    OK        B9_apostrophe_desync_then_real_backtick | expected='git_push' actual='git_push'
    OK        B10_piped_opener_line | expected='git_push' actual='git_push'
    KNOWN_GAP B11_real_push_on_opener_line | expected='git_push' actual=None
    OK        B12_real_full_pytest | expected='full_test' actual='full_test'
    OK        B13_python_dash_m_pytest | expected='full_test' actual='full_test'
    OK        B14_python_payload_shell_call | expected='git_push' actual='git_push'
    == classify_review_gate_command ==
    OK        C01_pytest_version_python_m | expected=None actual=None
    OK        C02_pytest_version | expected=None actual=None
    OK        C03_pytest_capital_v | expected=None actual=None
    OK        C04_pytest_co | expected=None actual=None
    OK        C05_pytest_collect_only | expected=None actual=None
    OK        C06_pytest_h | expected=None actual=None
    OK        C07_pytest_help | expected=None actual=None
    OK        C08_observed_1605_chain | expected=None actual=None
    OK        C09_version_then_real | expected='full_test' actual='full_test'
    OK        C10_real_then_version | expected='full_test' actual='full_test'
    OK        C11_echo_version_then_real | expected='full_test' actual='full_test'
    OK        C12_version_piped_then_real | expected='full_test' actual='full_test'
    OK        C13_flag_in_other_segment | expected='full_test' actual='full_test'
    OK        C14_real_full_pytest | expected='full_test' actual='full_test'
    OK        C15_real_push | expected='git_push' actual='git_push'
    mismatches = 0 known_gaps_open = 1 of 33

## 4. 双向结论

| 方向 | 用例 | 修前 | 修后 |
|---|---|---|---|
| 目标场景放行 | A1 正文 Markdown 代码span 含 `git push origin main` | `git_push`（误拒） | `None` |
| 目标场景放行 | A2 多行 Markdown 列表项 | `git_push`（误拒） | `None` |
| 目标场景放行 | A3 体内撇号 + 代码span | `None`（引号状态失步的巧合，不是正确豁免） | `None` |
| 目标场景放行 | A4 正文代码span 含 `pytest -q` | `full_test`（误拒） | `None` |
| 目标场景放行 | C01–C08 pytest 非执行形态 | `full_test` | `None` |
| 应拦仍拦 | B1 真实 push | `git_push` | `git_push` |
| 应拦仍拦 | B2 骨架内真实反引号替换 | `git_push` | `git_push` |
| 应拦仍拦 | B3 无引号终止符的体 | `git_push` | `git_push` |
| 应拦仍拦 | B4 非数据接收者 | `git_push` | `git_push` |
| 应拦仍拦 | B5 豁免体之后的真实 push | `git_push` | `git_push` |
| 应拦仍拦 | B6、B7 引导落在跨行引号串内 | `git_push` | `git_push` |
| 应拦仍拦 | B8 终止符未配对 | `git_push` | `git_push` |
| 应拦仍拦 | B10 opener 行带管道 | `git_push` | `git_push` |
| 应拦仍拦 | B12、B13 真实全量 pytest | `full_test` | `full_test` |
| 应拦仍拦 | B14 python 载荷内 shell 调用 | `git_push` | `git_push` |
| 应拦仍拦 | C09–C13 同串含真实 pytest 调用 | `full_test` | `full_test` |
| 应拦仍拦 | C15 真实 push | `git_push` | `git_push` |
| 同批闭合的漏放 | B9 豁免体内撇号，其后真实反引号替换 | `None`（漏放） | `git_push` |

## 5. 单元测试（红到绿）

- 修复前：`tests/unit/test_review_gate.py` 与 `tests/unit/test_review_host_admission.py` 得 **7 failed / 311 passed**，失败项恰为新增用例。其中 `test_exempt_heredoc_markdown_backtick_span_not_admitted_as_push` 经 `HostReviewAdmission.check_shell` 复现了 17:11 的拒绝原文。
- 修复后首轮（加 `tests/unit/test_arch_guards.py`）：369 passed / 1 failed。失败的是一条既有用例，它拿 `pytest --version` 当「能快速退出的全量测试命令」的替身，而这个替身正是本次要改掉的误分类。处理：不删断言，把替身换成临时目录里一次真实但最小的全量 pytest（一个必过用例），并补「`pytest --version` 不再带观测行」的反向断言。`test_review_gate.py` 单独复跑 13 passed，三文件合计 370 条通过。
- `ruff check`（只读，未做全文件格式化）通过。

## 6. 已知缺口（本次不修，另行提演进建议）

- **B11**：`cat > f <<'EOF'; git push origin main` 换行后接正文。opener 行 `<<'EOF'` 之后的文本在生成骨架时被丢弃，段网看不到其后的真实动作。基线与被测均为 `None`，本次改动未使其变化。属收紧方向，不在已批准范围内。
- 引导落在跨行引号串内时的内容网豁免（`$(...)` 形态）同理未并入（见偏离 5）。

## 7. 待办

- 真实入口活体验证（部署后）：`execute_command` 下正文含 Markdown 代码span 的写文档命令不再被拒；真实 push 与全量测试命令在无资格时仍被拒。
- `evolution_complete` 登记（注明上述偏离与 B11 缺口）。

## 8. 接力修复（2026-11-26，独立审查 P1）

合入前复验时，push 闸（`subagent_3c3885323858`）与后续 lane 的 full_test 闸（`subagent_801ecd8bf25d`）各返回 1 条 P1，均为 REVISE，未放行。两条先用分类器与真实 bash 复现，确认后再修。修后定向单测 327 passed（原 318，新增 9 条）；全量门禁见 `full-test-gate-evo-86a9864e-20261125.json`。下表「基线」取 main `a4623895`（这两个文件与 `c6612c7e9` 相同）。

### 8.1 P1-A：非执行判定放过藏在引号 / `bash -c` 载荷里的真实调用

`_PYTEST_CMD_RE` 的命中只收命令位的调用。`pytest --version; bash -c 'pytest -q'` 的唯一命中是诱饵 `pytest --version`，「全部非执行」成立，被判 `None`，而 `pytest -q` 会被 shell 真实执行。这是本次改动新引入的 fail-open。

修法：把全部命中的文本挖掉后，若仍残留 pytest 词元（排除 `pytest-xdist` / `pytest_cov` 这类包名片段），不断言非执行，回到全量闸面。

| 用例 | 基线 | 本 lane 修复前 | 修复后 |
|---|---|---|---|
| `pytest --version; bash -c 'pytest -q'` | `full_test` | `None`（新漏放） | `full_test` |
| `pytest --co && sh -c 'pytest'` | `full_test` | `None`（新漏放） | `full_test` |
| `python -m pytest -h; python -c 'import pytest, sys; pytest.main()'` | `full_test` | `None`（新漏放） | `full_test` |
| `pytest --version; pip install pytest-xdist` | `full_test` | `None` | `None`（保持放行） |
| `pip install pytest==8.0.0`（无命令位命中） | `None` | `None` | `None` |

同批收紧 P2-3（旗标须是该次调用的选项）：`pytest "my --version file"` 与 `pytest -- -h` 的旗标文本在引号串里或 `--` 之后，修复前被判非执行，现归全量闸面；`pytest --version "out --help.txt"` 保持放行。P2-1 的 `--co` 导入副作用边界已在正则注释中声明，口径不改。

### 8.2 P1-B：opener 行尾留下未闭合引号时体被脱敏

审查者给的原样例（行尾 `; echo "note`）含 `;`，本就被判非豁免，不是洞。但它指向的根因成立：豁免与「引导位于顶层」只看 `<<` 之前的文本，`<<WORD` 之后的行尾文本不检查引号状态。行尾不含 `;&|()` 却留下未闭合引号时（如 `> "note`），shell 把后续各行当作该引号串的延续——属于命令行，不是 here-doc 体，双引号内的命令替换真实执行。分类器却把这些行当作可豁免的体，从反引号网与内容网脱敏。

真实 bash 实测（无害的 `touch` 标记代替受保护动作，2026-11-26 01:47）：

    cat > doc_p1b.md <<'EOF' > "note
    `touch marker_p1b` x"
    EOF

结果：`MARKER_CREATED: command substitution ran`，`doc_p1b.md` 为 0 字节。

修法：`data_body = is_exempt 且 opener 行尾引号状态收在顶层`，同时用于内容网豁免与反引号网脱敏。体的反引号替换均为 `` `git push origin main` ``。

| opener 行 | 基线 | 本 lane 修复前 | 修复后 |
|---|---|---|---|
| `cat > f <<'EOF' > "note` | `git_push` | `None`（新漏放） | `git_push` |
| 同上，其后另有一行使骨架引号配平 | `git_push` | `None`（新漏放） | `git_push` |
| `cat <<'EOF' 'arg` | `None` | `None` | `git_push`（保守过拦：真实 bash 也不执行，接受） |
| `cat > f <<'EOF' > "a b"`（引号已闭合） | `git_push`（误拒） | `None` | `None` |
| `cat > f <<'EOF' # it's fine` | `None` | `None` | `None` |
| `cat > f <<'EOF' 2>/dev/null` | `git_push`（误拒） | `None` | `None` |
| `cat > f <<'EOF' && echo done` | `git_push` | `git_push` | `git_push` |

### 8.3 顺带发现（未修，不在已批准范围）

Host 准入分类器对 `pytest -- -h` 返回 `None`（`--` 之后的 `-h` 被当作 help 旗标），而真实 pytest 会跑全量。基线与修后一致，属既有缺口，另行提演进建议。

## 9. 接力修复 2（2026-11-26，合并审查 REVISE）

verify 绑定过期后重做独立合并审查（`subagent_30e3d30f3a05`，glm/glm-5.3），终态 REVISE，P0=0 P1=1。合并审查者按设计只回结论 JSON、不附正文，且是隔离子代理（禁续话），P1 的具体内容取不到。处理：不另开一次审查去换结论，先对 base..head 的全部源码改动自查——用「分类器判定 × 真实 bash」差分实测，找出本 lane 相对 main 新增的漏放。

### 9.1 方法

探针原文：同目录 `evo-86a9864e-diffprobe-20261126.py.txt`（114 行）。30 个多行 shell 程序。同一段受保护动词在两种运行里互换：分类器侧是 `git push origin main`，bash 侧换成 `touch m`（无害标记），其余字符逐字相同。bash 侧以 `bash s.sh` 实跑后查标记文件是否出现，判定该动词位置是否被执行；分类器侧分别加载 main（`c6612c7e9`）与本 lane 工作树的模块。「bash 执行 + 分类器 `None`」记为漏放。

### 9.2 结果

「修前」= head `16e4230d3`，「修后」= 本节修复。P 表示受保护动词所在位置；反引号 / `$( )` 表示包在该形态内。

| # | 程序骨架 | 真实 bash | main | 修前 | 修后 |
|---|---|---|---|---|---|
| 01 | `cat <<<'EOF'` / `` `P` `` / `EOF` | 执行 | `git_push` | **`None`（新漏放）** | `git_push` |
| 02–07 | here-string（`<<<'EOF'`、`<<< 'EOF'`、`<<<"EOF"`、`cat -n`、`cat >f`、未闭合）+ P | 执行 | `None`（既有漏放） | `None` | `git_push` |
| 08 | `cat <<<'EOF'; P`（同一行） | 执行 | `None`（既有漏放） | `None` | `git_push` |
| 09–12 | 真 here-doc 引导行行尾 `;` / `&` / `&&` / `|` + P，其后接正文与终止符 | 执行 | `None` | `None` | `None`（§6 的 B11，由 lane-ffb64ade 修复） |
| 13–14 | `# \` 续行后接 `cat > f <<'EOF'`，体内 P / `` `P` `` | 不执行 | 13 `git_push`、14 `None` | `None` | `None` |
| 15 | `true # cat > f <<'EOF'` / P / `EOF` | 执行 | `git_push` | `git_push` | `git_push` |
| 16–17 | `$'a\'` 之后、`case` 模式位的引导，体内 `` `P` `` | 不执行 | `git_push` | `git_push` | `git_push`（保守过拦，既有） |
| 18 | `cat > n.md <<'EOF'` / Markdown 代码span / `EOF` | 不执行 | `None` | `None` | `None` |
| 19–20 | `cat > f <<'EOF'`，体内 `` `P` `` / `$(P)` | 不执行 | 19 `git_push`（误拒）、20 `None` | `None` | `None` |
| 21–22 | `cat <<EOF`（无引号终止符），体内 `` `P` `` / `$(P)` | 执行 | `git_push` | `git_push` | `git_push` |
| 23–24 | `cat \<<'EOF'`、`cat<<<'EOF'`，体内 `` `P` `` | 执行 | `git_push` | `git_push` | `git_push` |
| 25 | `cat > f <<'EOF' "note`（行尾未闭合引号），体内 `$(P)` | 不执行 | `None` | `git_push` | `git_push`（§8.2 的保守过拦） |
| 26 | `echo "x` 之后的引导，体内 `` `P` `` | 执行 | `git_push` | `git_push` | `git_push` |
| 27 | `cat 0<<'EOF'`，体内 `` `P` `` | 不执行 | `git_push`（误拒） | `None` | `None` |
| 28 | `echo "$(cat <<'EOF'` …，体内 `` `P` `` | 不执行 | `git_push` | `git_push` | `git_push`（保守过拦，既有） |
| 29–30 | 对照：裸 `` `P` ``、裸 P | 执行 | `git_push` | `git_push` | `git_push` |

相对 main，本 lane 修前唯一「main 拦、修前不拦、bash 执行」的用例是 01。

### 9.3 根因与修法

`_HEREDOC_OPENER_RE` 没有后顾，`cat <<<'EOF'` 会从第二个 `<` 起命中，here-string 被当成带引号终止符的 here-doc 引导；接收者 `cat` 在数据落点白名单内，于是其后的行被当作「已配对 + 豁免」的数据体。shell 里 here-string 没有正文，其后直到同名终止符行都是普通命令行（上表 01–08 的标记均被创建）。裸动词形态（02–08）在 main 上已漏放：内容网对这种「假体」的豁免是既有行为，本 lane 没有改变它。反引号形态（01）在 main 上由扫原始全文的反引号网兜住；本 lane 把该体移出反引号网之后才漏放——属本 lane 新引入的回归。

修法：正则加否定后顾 `(?<![<])`，`<<` 前紧邻 `<` 时不再是引导，该行与其后各行照常进骨架与反引号网。只收紧：应放行用例（13、14、18–20、27）修后仍为 `None`；here-string 之后再接真 here-doc（`cat <<< 'EOF' <<'X'`）照常豁免。

### 9.4 单元测试

两个测试模块修后 336 passed / 0 failed，133.70s（原 327，新增 9 条：参数化 8 条，`check_shell` 级端到端 1 条）。全量门禁见 `full-test-gate-evo-86a9864e-20261125.json` 的最新一次运行。

### 9.5 如实记录

- 合并审查者报的 P1 是否即本节所述，无法核实（审查者不附正文、不可续话）。本节是独立自查的结论，不代表已覆盖审查者的关注点。
- 用例 09–12（B11）修后仍漏放，由 lane-ffb64ade 承担；本 PR 合入到该 lane 合入之间，main 上这一形态与基线相同。
- 用例 16、17、25、28 是保守方向的过拦（真实 bash 不执行而分类器拒绝），未改。

