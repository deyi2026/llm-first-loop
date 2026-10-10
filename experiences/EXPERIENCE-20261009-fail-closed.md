---
title: "子进程门禁必须对\"静默成功\"fail-closed：要求正面输出证据而非仅退出码"
scenario: 给长生命周期 bash 运维脚本新增子进程预检（python -m ...），脚本按 LFL_RESTART_CODE_ROOT/RUNTIME_ROOT 环境或自身位置解析代码根；宿主 shell 可能残留上次权威操作注入的同名环境变量
root_cause: 环境变量泄漏（LFL_RESTART_CODE_ROOT）+ Python -m 对无 __main__ 的模块静默成功 + 门禁只看退出码不要求正面输出证据
solution: "门禁子进程调用一律 fail-closed 双条件：退出码 0 且 stdout 含唯一 PASS 标记（如\"校验通过\"）；无输出按\"校验通道失灵\"拒绝执行后续 mutating 步骤。冒烟时必须同时跑污染环境（env -u 清理前后）两种用例。"
evidence: "14:42:54 preflight 运行回执：`✅ runtime.toml schema preflight PASS: `（_out 为空，假 PASS）；同刻 venv 解析检查：has_main=False、r.__file__=.releases/987f8642f.../src；14:44:22 加固后复测：污染环境 ❌ 拒绝、干净环境 ✅ 带消息；提交 993f9c2f8（restart_mirror.sh fail-closed 段）；tests/unit/test_evo_9d116efa_restart_hardening.py 11 passed"
tags: [fail-closed, preflight, restart_mirror, 环境变量泄漏, python-m-静默成功, EVO-20261009-9d116efa]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-09T14:52:49.286301+08:00"
updated_at: "2026-10-09T14:52:49.286301+08:00"
---

在 restart_mirror.sh 加 schema 预检时初版只判 `python -m llm_loop.runtime.resolver --check-toml` 退出码：shell 环境残留 LFL_RESTART_CODE_ROOT=.releases/<旧sha>（上次 restart worker 派生的 env 泄漏进后续 execute_command）时，脚本把 CODE_ROOT 解析到旧 release，PYTHONPATH 指向的 resolver 是无 __main__ 入口的旧版——`-m` 静默 exit 0、零输出，预检假 PASS（与脚本 245-248 行 WEB_PORT 同型陷阱）。修复：命令替换捕获输出 + 退出码，输出必须含明确 PASS 标记（"校验通过"）否则一律拒绝。教训：任何"调用子进程做门禁"的预检，退出码 0 且无输出≠校验通过，必须要求正面证据（显式输出标记），否则旧版本静默吞掉失败。