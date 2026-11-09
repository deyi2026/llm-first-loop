---
title: env 访问棘轮：新增配置项时应把读取点收敛到 config 的既有 env_values alias，而不是在策略层读 env
scenario: "在仓库里新增一个环境变量配置项（如 LFL_PEER_WRITE_ROOT），被 tests/unit/test_runtime_env_access_gate.py 判定为\"直接 env 访问新增\"，access_count 超出基线 1 条。"
root_cause: "runtime env 访问单向棘轮按「文件|函数|动作|key」计签名。安全策略模块直接 os.environ.get(新键) 会新增直接访问签名并破棘轮。而 config 里既有的 `env_values = os.environ if env is None else env` 是 alias，scanner alias-aware，把它记为一条 bulk 签名；同一函数内再 .get(新键) 不新增签名。因此\"读取点收敛到 config 的既有 alias\"既能去掉策略层的 env 依赖，又不加债。"
solution: |
  1) 不要在策略/业务模块读 env（WriteGate 这类模块改成只接受注入值，None=未配置即 fail-closed）。2) 在 config.load_settings 里用既有的 env_values alias 增加一行 `field=env_values.get("NEW_KEY", "").strip()`——不新增签名，access_count 不变。3) 装配点（web/__init__.py、独立服务入口）把值注入下去；独立脚本可用显式 CLI 参数。4) 加一条"设了 env 也不生效、只有注入才生效"的测试钉住，防回落回潮（RULE-AI-35）。注意：若 config 那个函数是 legacy 超红线巨函数，新增一行会破函数行数棘轮，需同时净零（删一行冗余注释），不要重登记放宽红线。
  当前性验证：跑 `python3 scripts/audit_runtime_env.py --src src | tail -3` 应与 tests/fixtures/runtime_env_access_baseline.json 的 access_count 相等；再 `grep -n "peer_write_root" src/llm_loop/config.py` 确认读取点在该函数内、且 `grep -rn "os.environ" src/llm_loop/peer/` 无输出。
evidence: "修复前 python3 scripts/audit_runtime_env.py --src src → access_count=208；修复后 207（与基线一致）。tests/unit/test_runtime_env_access_gate.py 11 passed。探针实测：os.environ.get(\"X\") 计 1 条；env_values = os.environ if env is None else env 后 env_values.get(\"X\") 只计 1 条 bulk 签名。"
tags: [env-access-ratchet, config-layer, fail-closed, arch-guard]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T21:29:14.587908+08:00"
updated_at: "2026-11-08T21:29:14.587908+08:00"
---