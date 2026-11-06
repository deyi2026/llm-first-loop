# merge gate 回执 · GOAL-20261106-a6fde1bf

- 审查者：独立合并审查子代理 `subagent_d0221bec71a2`（GLM-5.3，只读，未参与分支产出）
- 任务书：`skills/merge-review-gate/SKILL.md`
- 被审分支：`fix/wheel-install-correctness`（head `401b41ef93cb4ecd4f8c4277a70886a38d6a5658`）
- 基线：`main` = `bcbc106dd17a41e5893f30e180fa4a5489b2e336`（merge-base == main，未落后未分叉）

## 回执 JSON

```json
{
  "gate": "merge",
  "reviewer": "subagent_d0221bec71a2",
  "verdict": "PASS",
  "goal_id": "GOAL-20261106-a6fde1bf",
  "branch": "fix/wheel-install-correctness",
  "based_on_main": true,
  "commits": ["401b41ef93cb4ecd4f8c4277a70886a38d6a5658"],
  "merge_mode": "ff",
  "conflicts_resolved": [],
  "focused_gates": [
    "RULE-AI-28 review_admission(kind=full_test) x3 -> PASS（末轮 subagent_091a76884ba1 覆盖该树）",
    "canonical bash scripts/ci_gate.sh -> exit 0（job-fdea3fc832904b3981f7；ruff new=0 / env-pin PASS / pyright new=0 / tier0 / 全量 pytest）",
    "test_runtime_paths_bundle: 4 passed",
    "test_model_check_provider_prefix: 8 passed",
    "doctor|first_use|model_check|paths 子集: 201 passed"
  ],
  "main_sha_after": "401b41ef93cb4ecd4f8c4277a70886a38d6a5658",
  "branch_disposition": "deleted：单提交已 ff 入 main，reflog 可追溯",
  "verify_receipt_id": "lane-673b3dad:bcbc106d"
}
```

## 六条清单结论（审查者原文要点）

1. **完成证据 通过** — 末轮 RULE-AI-28（`subagent_091a76884ba1`）与 canonical 门禁 `job-fdea3fc832904b3981f7` 声明覆盖树 `401b41ef9`；审查者核得 worktree HEAD=401b41ef9 且树干净，与回执树一致。
2. **分支卫生 通过** — `status --porcelain` 为空；`main..branch` 仅 1 提交；diff --stat=5 文件 +413/-13 与声明清单一致；唯一 "password" 命中是 `urlsplit(base_url).password` 解析代码非密钥，`LLM_API_KEY` 仅为环境变量名。
3. **基线新鲜 通过** — `merge-base` == `rev-parse main` == `bcbc106dd1`，未落后未分叉。
4. **测试面 通过** — 定向门禁有回执（引用不重跑）；新测试实核覆盖：bundle 回退 / env 优先 / 源码树不变 / 无 bundle 时保持 code-root；已知前缀剥 / 未知保持 / 裸名不变 / wire 显式优先 / anthropic+google 协议 / base_url 推导 / MODEL_PROVIDERS 剥前缀。
5. **合并方式 通过** — 纯 ff 零冲突。
6. **合并后 通过** — 合并者在 `main` 跑 `pytest -k "runtime_paths_bundle or model_check_provider_prefix or doctor"` 冒烟并回填 `main_sha_after`；分支删除。

审查者抽查结论：`paths._asset_dir` 优先级 env -> code_root(`is_dir`) -> bundle（仅缺失时回退）；`model_check._wire_model` 仅当 prefix 属于已知 provider_ids 才剥，空段/未知前缀原样；`doctor._model_check_settings` 只取 merged 映射，grep 无新增 `os.environ`。

## 合并执行留痕

- 合并前 main：`bcbc106dd17a41e5893f30e180fa4a5489b2e336`
- 合并方式：`git merge --ff-only fix/wheel-install-correctness`（在 `.worktrees/merge-main` 的 main 上执行，避免扰动共享工作树）
- 合并后 main：`401b41ef93cb4ecd4f8c4277a70886a38d6a5658`
- 合并后 focused 冒烟：``pytest tests/unit -q -k "runtime_paths_bundle or model_check_provider_prefix or doctor"` → **31 passed, 10654 deselected**（在 main=401b41ef9 上执行，exit 0）`
- 主机侧影响：目标 Linux 主机（内网地址按隐私规则不在回执中记录）运行的是已发布 0.6.37 wheel，本合并不改变其运行版本；含该修复的新发行版发布后由主机侧升级并复验（见 `docs/minimax-linux-setup.md`）。
