---
title: 长跑 pytest 输出被截断时，用 lastfailed + 守卫纯函数定位失败（不重跑）
scenario: 后台跑长全量测试，job_output 只给到 88% 的截断输出，拿不到失败清单；需要不重跑、不重复过审查闸就定位失败
root_cause: ""
solution: exit_code 判通过；.pytest_cache/v/cache/lastfailed 判失败清单（过滤陈旧键）；守卫类测试直接 import 测试模块调其纯函数测量；必要时输出重定向到文件
evidence: "evidence://v1/a805d9ed0a4704b2a9aa8881ada11dd5ea7dcaa236e72cda947ca4102666ce96（全量 14120 passed exit=0）；evidence://v1/dda9aceb007fd36254d5a4ed6df258dbd572d15c006ba52fb43fb063775fdcfa（首轮 exit=1 但尾部丢失）；evidence://v1/26aee84eae0802c674b1de25efbbf549cc9cf3e9ed16c8bae0140282ba546bfb（lastfailed 仅剩 env 项）；evidence://v1/72ec09da68f7888d5c1ac74657102365f9d50f4250045ae066d4124c1dbf8062（补 .venv 后实测版本可见）"
tags: [pytest, 后台任务, 截断, 守卫测试, 诊断, worktree]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-08T01:49:20.323857+08:00"
updated_at: "2026-11-08T01:49:20.323857+08:00"
supersedes: [EXPERIENCE-20261009-identity-guard-p0-ratchet-baseline, EXPERIENCE-20260909-lfl-llm-pytest-tail]
---

## 场景
在 worktree 里跑 20 分钟级的全量 pytest，用 execute_command(run_in_background) + job_output 收结果。第一次 exit=1，但 job_output 只回了 220 行、停在 88%，`short test summary` 和 `FAILED ...` 全部落在被丢掉的尾部（read_evidence 分页到 220 行就 `next=end`）。

## 做法（可复用）
1. **判通过看 exit_code，不看输出尾部**：exit=0 就是通过；不要因为看不到 "N passed" 而怀疑。
2. **判失败清单读 pytest 自己的账本**：`<worktree>/.pytest_cache/v/cache/lastfailed` 是 JSON，键就是失败 node id。注意它会保留"曾经失败、本次未收集"的陈旧键（改名/删掉的用例），要按"当前是否存在该 node id"过滤。
3. **不要在 pytest 里定位违例**：守卫类测试（ruff/pyright 之外的自研 guard）大多是纯函数。直接 `importlib.util.spec_from_file_location` 加载测试模块、调它的 `_measure_*`/`_problem*` 并打印，比再跑一次 pytest 快 3 个数量级，而且不需要重新过 RULE-AI-28 审查闸（那不是"全量测试"，是只读诊断）。
4. 需要看真实失败消息时，把 pytest 输出**重定向到文件**再读；后台 job 的缓冲区会截中间/尾部。

## 本次实证
- 首轮 exit=1 → lastfailed 10 条 → 过滤掉 3 条陈旧键 → 4 类真实违例（peer/models.py 用 UTC 序列化、peer 包未登记 top_level_units、3 个持久化写入面未登记、2 条函数红线抬高）。
- 直接调守卫函数拿到 `src/llm_loop/peer/models.py:20 uses datetime.datetime.now(datetime.UTC)` 精确行号，一轮修完。
- 二轮 exit=1 只剩 1 条 `test_env_preflight` → 定位为 worktree 无 `.venv`（环境事实，非代码）；补软链后三轮 exit=0，14120 passed。

## 边界
- 只适用于 pytest；其它框架的失败账本不同。
- 守卫函数直接调用会绕过 monkeypatch fixture，用到 fixture 的用例还是要真跑 pytest。
- `lastfailed` 只在没加 `-p no:cacheprovider` 时写入。