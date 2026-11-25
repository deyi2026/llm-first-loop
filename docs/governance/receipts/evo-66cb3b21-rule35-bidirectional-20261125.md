# EVO-20261125-66cb3b21 · RULE-AI-35 双向实测回执

- 演进：EVO-20261125-66cb3b21（人工 2026-11-25 19:54 批准，`human_exec_override=true`，executor=ai）
- 变更性质：**收紧既有判定**，把此前不可见的一段命令文本纳入段网。按 RULE-AI-35 须证「新增拦截确实触发」与「既有豁免形态不被误拦」两侧。
- Goal / lane：GOAL-20261125-0f6d9a2b / lane-ffb64ade（分支 `fix/rule28-heredoc-opener-tail-20261125`）
- 叠放关系：本 lane 基于 lane-27aa2dc0（EVO-20261125-86a9864e）的 head `cf87b290f70518ca69ca753ba287e8fd7c1ae4bc`，须在其合入之后再合入。
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

