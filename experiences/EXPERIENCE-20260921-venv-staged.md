---
title: venv 解释器错位与守卫读 staged 内容导致门禁假绿/假失败
scenario: 在 llm-first-loop mirror 工作区内验证测试/门禁（pytest、tests/unit/test_arch_guards.py 棘轮守卫）时，结果出现与代码状态矛盾的假绿/假失败。
root_cause: ""
solution: 固定用 .venv/bin/python 跑 pytest；结果判定必须取完整摘要行（grep passed|failed），禁止 tail -1 截断；跑 tests/unit/test_arch_guards.py 前先 git add 暂存被改文件（守卫读 staged 内容，未暂存回退 git show HEAD）。
evidence: "evidence://v1/a132aab565dd2ecbeb45513931d0c3265a9537ffbc0f405a214431fba32776a71b（python3=lark 无 lark_oapi/.venv 有）；/tmp/gate_gap2_v2.log（GATE_EXIT=0）；commit 5df466c78"
tags: [testing, interpreter, venv, staged-content-guards, pytest]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-21T00:28:15.778604+08:00"
updated_at: "2026-09-21T00:28:15.778604+08:00"
---

现象：会话内用 `python3 -m pytest` 跑目标集"看起来全绿"（`tail -1` 只取到进度点行），但部分用例实际 FAILED；单跑某用例失败时 traceback 是 ModuleNotFoundError: lark_oapi。事实链：① harness 的 `python3` 是 /opt/homebrew/bin/python3（无 lark_oapi），仓库依赖在 .venv（Python 3.13）；PYTHONPATH=src 使 llm_loop 可导入，掩盖了解释器错位；② `-q` 模式下 FAILED 摘要行在进度行之后，`tail -1` 恰好截掉；③ tests/unit/test_arch_guards.py 的守卫读 staged 内容：文件未 git add 时回退 `git show HEAD:<rel>`，改完源码不暂存就跑守卫会测到旧代码。处置：测试一律 `.venv/bin/python -m pytest`；判断通过/失败必须取完整摘要行（grep -E "passed|failed"）而非 tail -1；跑架构守卫前先 git add。验证：.venv 解释器下目标集 71 passed；git add 后 test_arch_guards 14 passed；提交 5df466c78 门禁 GATE_EXIT=0。