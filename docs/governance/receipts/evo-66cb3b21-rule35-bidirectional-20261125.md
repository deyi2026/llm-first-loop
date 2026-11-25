# EVO-20261125-66cb3b21 · RULE-AI-35 双向实测回执

- 演进：EVO-20261125-66cb3b21（人工 2026-11-25 19:54 批准，`human_exec_override=true`，executor=ai）
- 变更性质：**收紧既有判定**，把此前不可见的一段命令文本纳入段网。按 RULE-AI-35 须证「新增拦截确实触发」与「既有豁免形态不被误拦」两侧。
- Goal / lane：GOAL-20261125-0f6d9a2b / lane-ffb64ade（分支 `fix/rule28-heredoc-opener-tail-20261125`）
- 叠放关系：本 lane 基于 lane-27aa2dc0（EVO-20261125-86a9864e），须在其合入之后再合入。原始基线为其 head `cf87b290f70518ca69ca753ba287e8fd7c1ae4bc`；2026-11-26 接力修复后更新为 `5e4c779094b9e82cd03d775917930cb29052e906`（见 §7）。
- **证据层级：本地实测**（分类器直调）。真实入口活体验证待部署后进行（TASK-0f6d9a2b-004）。

## 1. 问题

`_strip_heredoc_units` 生成骨架时，opener 行只保留 `<<` 之前的 head，再把体替换成占位 token。heredoc 引导之后、同一行上的文本被整段丢弃，而它在 shell 中会被正常解析执行：

    cat > /tmp/doc.md <<'EOF'; git push origin main
    正文
    EOF

段网只看骨架，因此对该命令返回 None，不进入 RULE-AI-28 准入。

## 2. 修法

opener 行的骨架改为「head + 占位 token + 引导之后的文本」，未闭合分支同样处理。净增 6 行，`_strip_heredoc_units` 实测 106 行（未登记，阈值 120）。反引号网与 net_out 镜像未改。

## 3. 探针与两侧输出

探针：同目录 `evo-66cb3b21-probe-20261125.py.txt`，sha256 `914565a5c3a343c42aa22678ac49e6bee513cd4b22751a4603d6083fa4ba4bd6`（55 行）。修前取 lane-27aa2dc0 head 的 src（含 86a9864e、不含本修复），修后取本 lane 工作树。

### 修前 —— 退出码 1

    MISMATCH T1_tail_semicolon_push | expected='git_push' actual=None
               skeleton='cat > /tmp/doc.md __XPL_0__'
    MISMATCH T2_tail_andand_push | expected='git_push' actual=None
               skeleton='cat > /tmp/doc.md __XPL_0__'
    MISMATCH T3_tail_semicolon_pytest | expected='full_test' actual=None
               skeleton='cat > /tmp/doc.md __XPL_0__'
    MISMATCH T4_tail_push_unterminated | expected='git_push' actual=None
               skeleton='cat > /tmp/doc.md __XPL_0__'
    MISMATCH T5_tail_redirect_then_push | expected='git_push' actual=None
               skeleton='cat > /tmp/doc.md __XPL_0__'
    OK       U1_tail_redirect_out | expected=None actual=None
    OK       U2_tail_redirect_err | expected=None actual=None
    OK       U3_tail_comment | expected=None actual=None
    OK       U4_tee_tail_redirect | expected=None actual=None
    OK       U5_command_after_terminator | expected=None actual=None
    OK       U6_markdown_code_span_body | expected=None actual=None
    OK       M1_unquoted_delimiter_body | expected='git_push' actual='git_push'
    OK       M2_real_push | expected='git_push' actual='git_push'
    OK       M3_tail_backtick_substitution | expected='git_push' actual='git_push'
    mismatches = 5 of 14

### 修后 —— 退出码 0

    OK       T1_tail_semicolon_push | expected='git_push' actual='git_push'
             skeleton='cat > /tmp/doc.md __XPL_0__ ; git push origin main'
    OK       T2_tail_andand_push | expected='git_push' actual='git_push'
             skeleton='cat > /tmp/doc.md __XPL_0__  && git push origin main'
    OK       T3_tail_semicolon_pytest | expected='full_test' actual='full_test'
             skeleton='cat > /tmp/doc.md __XPL_0__ ; pytest -q'
    OK       T4_tail_push_unterminated | expected='git_push' actual='git_push'
             skeleton='cat > /tmp/doc.md __XPL_0__ ; git push origin main'
    OK       T5_tail_redirect_then_push | expected='git_push' actual='git_push'
             skeleton='cat > /tmp/doc.md __XPL_0__  > /tmp/out; git push origin main'
    OK       U1_tail_redirect_out | expected=None actual=None
    OK       U2_tail_redirect_err | expected=None actual=None
    OK       U3_tail_comment | expected=None actual=None
    OK       U4_tee_tail_redirect | expected=None actual=None
    OK       U5_command_after_terminator | expected=None actual=None
    OK       U6_markdown_code_span_body | expected=None actual=None
    OK       M1_unquoted_delimiter_body | expected='git_push' actual='git_push'
    OK       M2_real_push | expected='git_push' actual='git_push'
    OK       M3_tail_backtick_substitution | expected='git_push' actual='git_push'
    mismatches = 0 of 14

## 4. 双向结论

| 方向 | 用例 | 修前 | 修后 |
|---|---|---|---|
| 新增拦截确实触发 | T1 后接 `; git push origin main` | None（漏放） | `git_push` |
| 新增拦截确实触发 | T2 后接 `&& git push origin main` | None（漏放） | `git_push` |
| 新增拦截确实触发 | T3 后接 `; pytest -q` | None（漏放） | `full_test` |
| 新增拦截确实触发 | T4 同 T1，且终止符未配对 | None（漏放） | `git_push` |
| 新增拦截确实触发 | T5 重定向后接 `; git push origin main` | None（漏放） | `git_push` |
| 既有豁免不被误拦 | U1 后续文本是 `> /tmp/out` | None | None |
| 既有豁免不被误拦 | U2 后续文本是 `2>> /tmp/err` | None | None |
| 既有豁免不被误拦 | U3 后续文本是注释，注释里含受保护字样 | None | None |
| 既有豁免不被误拦 | U4 `tee … >> /tmp/b.md` | None | None |
| 既有豁免不被误拦 | U5 命令在终止符行之后 | None | None |
| 既有豁免不被误拦 | U6 正文 Markdown 代码span（86a9864e 的目标场景） | None | None |
| 应拦仍拦 | M1 无引号终止符的体 | `git_push` | `git_push` |
| 应拦仍拦 | M2 真实 push | `git_push` | `git_push` |
| 应拦仍拦 | M3 引导之后的反引号替换 | `git_push` | `git_push` |

单元测试：修复前 5 failed / 85 passed，失败项恰为 5 条目标场景；修复后 `test_review_host_admission.py`、`test_review_gate.py`、`test_arch_guards.py` 共 **380 passed**。`ruff check`（只读）通过。

## 5. 已知边界

- 建议原文即已声明：命令闸（lane_main_write_guard，另有一套 heredoc 剥离）与 `.githooks/pre-push` 是否覆盖此形态，本次未验证。本条只处理 Host 准入分类器自身。
- 同一行出现第二个 heredoc 引导（`cat <<'A' <<'B'`）时，第二个引导作为普通文本进入骨架，其体仍按普通行进入骨架被扫描（保守方向），未做专门建模。

## 6. 待办

- 真实入口活体验证（部署后）：opener 行带后续受保护动作的写文档命令被拒；纯写文档命令（带重定向或注释）仍正常执行。
- `evolution_complete` 登记。

## 7. 接力修复（2026-11-26，独立审查 P1）

合入前复验时，full_test 闸（`subagent_801ecd8bf25d`）对本 lane 返回 REVISE：P1=1、P2=1。

**P1（成立，根因在 lane-27aa2dc0 一侧）**：审查者的原样例是行尾 `; echo "note` 后接体。它含 `;`，本就被判非豁免，不是洞。但根因成立：豁免与「引导位于顶层」只看 `<<` 之前的文本，行尾文本留下未闭合引号时不检查——行尾不含 `;&|()` 而留下未闭合引号（如 `> "note`）时，shell 把后续各行当作引号串延续，双引号内命令替换真实执行（真实 bash 实测，见 lane-27aa2dc0 回执 §8.2）。本 lane 修前对这些形态也返回 `git_push`，但靠的是行尾文本进骨架后骨架词法失败、退回全文扫描——结论对，机制靠兜底。

修法在 lane-27aa2dc0（`5e4c77909`）：`data_body = is_exempt 且 opener 行尾引号状态收在顶层`，同时约束内容网豁免与反引号网脱敏。本 lane 已合并该提交，`_strip_heredoc_units` 两处冲突按「保留本 lane 的 `out.append(skeleton_line)` + 采用对侧 `data_body`」解决，行尾变量合并为一个 `tail`。合并后由顶层条件本身拦下，不再依赖兜底。

| 用例（体的反引号替换均为 `` `git push origin main` ``） | 合并前（8f7b55542） | 合并后 |
|---|---|---|
| 行尾 `> "note` | `git_push`（靠兜底） | `git_push`（顶层条件） |
| 行尾 `> "note`，其后一行使骨架引号配平 | `git_push`（靠兜底） | `git_push`（顶层条件） |
| 审查者原样例：行尾 `; echo "note` | `git_push` | `git_push` |
| 行尾 `> out.md`、`# 注释`、`2>/dev/null` | `None` | `None` |

**P2（不成立，表述已改精确）**：审查者称 `classify_host_shell` 文档串声明 ValueError 兜底扫原始全文、实现却扫 `net_text`。实现扫的是 `value`（原始命令文本）。文档串已改写为显式点名 `value`，并补上「opener 行整行收在顶层」条件。

新增测试：参数化 2 条、`check_shell` 级 1 条（含「骨架可词法分析时仍被拦」与「行尾真实动作对段网可见」两个断言）。叠放基线更新为 lane-27aa2dc0 head `5e4c77909`。

