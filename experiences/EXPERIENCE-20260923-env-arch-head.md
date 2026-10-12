---
title: 仓内全量单测三条坑：错解释器、服务 env 污染、arch 守卫读 HEAD
scenario: 在 LFL 运行时会话内跑仓内全量单测（llm-first-loop-mirror）作为发布门禁
root_cause: ""
solution: 用 .venv/bin/python -m pytest tests/unit；对假设干净 env 的测试在测试内 monkeypatch.delenv 覆盖键；守卫显式覆盖 macOS /var/folders；改 src 后先 git add 再看棘轮计数
evidence: "job-49d9b3f（.venv 全量，6 失败清单）；evidence://v1/e8a6b5e8（env 泄漏复现：experiences dir 解析到真实根）；evidence://v1/b0acc9e6（_read_source HEAD 回退实现）；job-8a0496f4（修复后全量 exit=0）"
tags: [pytest, venv, 环境隔离, 棘轮, arch-guards]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-23T16:52:38.713703+08:00"
updated_at: "2026-09-23T16:52:38.713703+08:00"
---

本仓全量单测必须用 .venv/bin/python（依赖齐全：pypdf/lark_oapi/reportlab）；系统 python3 会有 16 个 collection error。LFL 运行时会话内的 execute_command 带重启契约 env（EXPERIENCES_DIR/LFL_DATA_DIR/LFL_RUNTIME_ROOT/TMPDIR=.tmp 指向真实工作区）：(1) 会破坏假设干净 env 的测试隔离——test_runtime_manifest 实测 knowledge_health 297 vs 1，修法是测试内 monkeypatch.delenv 覆盖键；(2) TMPDIR 改写会让 _cwd_in_system_temp 漏判 macOS /private/var/folders 下的 pytest 临时区——守卫已显式覆盖 /var/folders 前缀。另外 test_arch_guards/_read_source 对 ' M'（未 staged）src 回退读 HEAD：改完 src 必须 git add 后 ratchet（函数内 import 63 棘轮、env 访问基线）才按工作树计数，否则看似修了仍报 63→65。