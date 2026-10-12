---
title: 公开分发快照的终检必须在导出后的树上执行，不能用原工作区测试结果替代
scenario: "公开库删库重建为单提交快照（b0e0eb5，v0.6.31）后首轮 GitHub Actions 门禁失败：test_rule_presence_contract.py::test_ledger_covers_all_sot_rules 因 FileNotFoundError（.codeartsdoer/specs/rule_presence/rule-presence-ledger.md 不存在于公开导出树）失败。发布终检曾在原工作区跑全量 pytest 全绿，但原工作区含 .codeartsdoer 内部治理目录，导出树不含，环境差异未被预检覆盖。"
root_cause: ""
solution: "修复与纪律：1) 引用内部治理目录的测试必须有\"开源分发环境条件跳过\"口径（对齐 test_docs_sync 既有模式：模块级 _AVAILABLE = path.is_file() + @pytest.mark.skipif）；2) 快照导出类发布的验证必须在导出后的树上跑（clone 公开库 + PYTHONPATH 指向导出树 + 原工作区 venv 的 python 复跑关键测试面），不能用原工作区全绿结果替代；3) 单提交快照更新走 clone→变更→amend→force push，变更同步 commit 到开发库真值历史。"
evidence: "https://github.com/deyi2026/llm-first-loop/actions/runs/38190293462（失败：FileNotFoundError rule-presence-ledger.md，8239 passed 1 failed）；https://github.com/deyi2026/llm-first-loop/actions/runs/38191331741（修复后 success 11m25s，门禁+安全扫描全绿）；开发库 commit 555dd11cc（fix(ci-public) + CHANGELOG 追记）；双环境验证回执：原工作区 20 passed、公开树 19 passed + 1 skipped"
tags: [ci, public-release, snapshot-export, test-skip-contract, verification-discipline]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-12T09:48:34.055119+08:00"
updated_at: "2026-10-12T09:48:34.055119+08:00"
supersedes: [EXPERIENCE-20261009-llm-first-loop-vs-releases-pytest-pythonpath-impor]
---

场景：删库重建/单提交快照导出公开分发（squash 快照 + force push）后的 CI 验证。

教训核心：上一轮发布终检在**原工作区**跑全量 pytest（7818 passed）就声称可发布，但原工作区含 `.codeartsdoer/` 内部治理目录；公开导出树按治理约定**不含该目录**，`tests/unit/test_rule_presence_contract.py::test_ledger_covers_all_sot_rules` 直接读 `.codeartsdoer/specs/rule_presence/rule-presence-ledger.md` → 公开库 CI FileNotFoundError，8239 passed 中唯一失败，门禁红了 11 分钟才暴露。

修复：对齐 `tests/unit/test_docs_sync.py` 既有口径——模块级 `_XXX_AVAILABLE = _path.is_file()` + `@pytest.mark.skipif(not _XXX_AVAILABLE, reason="开源仓库不含内部治理目录")`；内部环境照常执行，开源分发环境条件跳过。

正确做法（导出类发布验证纪律）：
1. 快照导出后，在**导出后的树**（git clone 公开库或导出工作区）复跑门禁关键面，不能用原工作区结果替代——环境差异（内部目录、ignored 文件、依赖路径）正是公开环境会踩的坑。
2. 检索导出树中引用被排除目录的测试：`grep -rln '<被排除目录名>' tests/`，逐个确认有 skip 口径（本次 test_docs_sync 有、test_rule_presence_contract 没有）。
3. 跨环境验证模板：原工作区跑=实际执行通过；`PYTHONPATH=<导出树> <原区venv>/python -m pytest <目标测试> -q` = 条件 skip 生效。

单提交快照更新方式（历史无关，不能直接 push）：clone 公开库 → 应用变更 → `git commit --amend --no-edit`（保持单提交）→ force push；变更应同时在开发库（本地真值）commit，保持两库内容一致。