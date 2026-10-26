---
title: web 会话内跑 ci_gate 全量测试须剔除 LFL_ENV_FILE（否则 test_cli_main_finally_closes_engine 假失败）
scenario: LFL web 服务进程内会话（我）通过 execute_command 运行全量测试门禁 scripts/ci_gate.sh，会话环境变量 LFL_ENV_FILE 泄漏进 xdist worker，导致唯一一个 mock 签名不兼容的测试确定性失败（2026-10-17 main b9bf967d8 验证）
root_cause: ""
solution: 从 web 会话跑全量门禁时用 `env -u LFL_ENV_FILE bash scripts/ci_gate.sh`（可再评估剔除全部 LFL_*）；测试失败先做单文件复现对照（设/不设该变量）再定性；注意 Rule28 准入按命令字符串逐字绑定，改命令需重新 review_admission；worktree 跑完测试后需 git restore . + git clean -xdf 再准入/发布（首轮残留会使准入封包超 192kb、publish 拒绝）
evidence: "evidence://v1/d3a7a39230c36e8fba1bcf02146e5da0d0cfa61b8eb5a0baa9548740c435c1b6；evidence://v1/a6d0d5d1666a8b138199becb36bd56ef36c961691d6990e612fc918c05ab7d51"
tags: [ci_gate, 环境泄漏, LFL_ENV_FILE, 全量测试, RULE-AI-28]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-17T13:13:26.338555+08:00"
updated_at: "2026-10-17T13:13:26.338555+08:00"
---

在 web 会话内用 execute_command 跑仓库 scripts/ci_gate.sh 时，进程环境带 LFL_ENV_FILE=<workspace>/.env（web 运行态注入）。tests/unit/test_llm_client_close.py::test_cli_main_finally_closes_engine 以 lambda: None mock llm_loop.config.load_env_file，而 cli.main 在 LFL_ENV_FILE 存在时会 load_env_file(env_file)（带参调用）→ 确定性 TypeError 失败。干净环境（env -u LFL_ENV_FILE）该文件 20/20 全过。首轮 9341 passed/1 failed 即此因，剔除后 9342 passed/0 failed。注意：ci_gate 只隔离 HOME+自注入 PYTHONPATH，不清洗 LFL_* 环境变量；且命令字符串与 Rule28 准入逐字绑定，env -u 前缀需重新准入。后续修复方向：该测试应 monkeypatch.delenv("LFL_ENV_FILE") 或 mock 接受参数。