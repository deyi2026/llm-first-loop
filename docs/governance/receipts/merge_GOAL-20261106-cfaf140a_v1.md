# 合并审查回执（RULE-AI-34 / merge-review-gate）——lane m1-escalation-trust

```json
{
  "gate": "merge",
  "verdict": "PASS",
  "goal_id": "GOAL-20261106-cfaf140a",
  "reviewed_at": "2026-11-06T14:54:17+08:00",
  "reviewers": [
    "subagent_660af501cec9 (merge-review-gate SKILL)——5 commit 全量审查 + PASS 链/审计事件/原始 ci_gate 输出一级证据核验（与分支产出零参与）"
  ],
  "branches": {
    "m1-escalation-trust": {
      "commits": [
        "9126e91e78d820559bb76a29fce35733663cb08f (M1 六项修复 ESC-03/04/05/07/08/09)",
        "e09fde130c7eb09b08dda48ce331c161cfed21cb (R1 复审修复：P1 detail 判别冲突 + P2×5)",
        "a844cafa7b4e97b6c88f0945e8565a5045e02f71 (lint ratchet 纯机械修复)",
        "c10ac276d909bd647aca395c1e7298d981383995 (ci_gate 两新红归因：baseline 登记 + .venv 锚)",
        "82eac754121ec858398de4a85b8a221fa9aca9c3 (docs-only 验证凭证)"
      ],
      "merge_base": "f575846ff2e461949e5fd59c2cb6cd5915e111eb（分叉基点；main 已前进：委派时 10fab6432 → 审查中 0bf687c2c）",
      "tree_clean": true,
      "diff_surface": "9 文件：tools/escalation.py、tools/builtin/escalation.py、web/routes.py、EscalationCenter.tsx(+test.tsx)、tests/unit/test_escalation_m1_trust.py、tests/test_escalation_m1_web.py、tests/fixtures/runtime_env_access_baseline.json、docs/verification/verify-m1-escalation-trust.md——全部与 M1 范围吻合，无夹带"
    }
  },
  "merge_mode": "merge-commit（main 在审查期间前进，不可 ff）。merge-tree 预演：vs 10fab6432 = aa67ef4039ec5fdf89363af8d2c002f8b8705fd3（与委派声明一致）；vs 当前 main 0bf687c2c = 51a2b9034b3767df6c7e8f6617892bc3587055f7；两者均 exit 0 零冲突。分支与 main 侧 4 新提交（1f0a94e15/96086f5d2/10fab6432/0bf687c2c）文件集完全不相交（comm -12 为空）。",
  "evidence_spot_checks": {
    "独立审查链（一级证据=父会话 8ce6aa41 append-only 事件日志）": "R1 ab69e6f644ad REVISE @13:46:47（报告文件在库，P1×1 detail 判别冲突+P2×5，reviewer sha 9ff8b2e9…）→ R2 a7971b7afcdd PASS @13:53:22（candidate_sha256=a4c534d7…，p2=1）→ R3 5e47bf5fe0c1 PASS @13:59:08（candidate_sha256=ad1fa92f…，p2=3）→ R4 f4a118dea6c9 PASS @14:21:20（candidate_sha256=24fec9977cf4…，p2=3）。三条 review_admission_qualified 均 review_qualification_verified=true；R4 start 载荷确认冻结 8 路径（含 tests/fixtures/runtime_env_access_baseline.json），target_name 覆盖 9126+e09f+a844+c10ac 全部内容提交。",
    "ci_gate 真实性": "/tmp/ci_gate_out.dYD3vA（14:27:40，worktree .venv）第 496 行原文『13847 passed, 158 skipped, 3 xfailed, 33 warnings in 229.74s』，与凭证逐字一致；tier0 [4/5] 收集异常在父日志中如实排查登记（非提交门禁，[5/5] 全量为权威出口）。",
    "fail-closed（ESC-04）": "consume 与 consume_for_execution 双路径：到期时间缺失/不可解析 → 置 expired+清空 token+记 token_invalid_expiry 日志+拒绝；不再由工具名/命令哈希兜底放行。测试覆盖两条路径（test_consume_rejects_missing/corrupt_expiry_fail_closed + 清 token 断言）。",
    "统一投影（ESC-09）": "_effective_status 在 get/list/wait_for_decision/_public（含新 detail 端点经 store.get）全路径生效；e09fde130 采纳复审 P2-2：approved+到期缺失/损坏 → 一律投影 expired，与 consume fail-closed 三层一致（消除边界翻转）。",
    "幂等排除（ESC-03）": "create 幂等复用条件加 not _sig_unverified；wait 工具对失效记录立即失败并提示重新申请；pending 专用查询与 pending_count 均排除失效记录（防误导与刷量）。测试用真实机制复现跨进程（更换 _STATE_SIGNING_KEY）。",
    "前端批准门（ESC-05/07）": "批准按钮 disabled={busy || !viewedFull}（截断命令必须先查看完整原文）；detail 失败判别用 error 字段+HTTP 码（P1 修复）+畸形 200 拒绝解锁 + 详情/列表指纹不一致拒绝（TOCTOU）；待审改 status=pending 专用查询穿透 50 条历史窗口（Panel 与 Watcher 双路径均有测试）；expected_sha256 回传绑定（后端 409 stale_review）。",
    "503 如实（ESC-08）": "list/detail 存储损坏/IO → 503+error，原始异常只入服务端日志（P2-1 修复后文案核对）；测试为真实损坏注入（corrupt json）+ chmod 000（root skipif 环境诚实）。",
    "baseline 登记正当性（c10ac276d）": "官方 --update-baseline 登记：registration_log 末条含 added_signatures（routes.py|escalation_detail|read|LFL_DATA_DIR）、cap 变化 206→207、parent_commit、reason、relaxations=true；routes.py 同文件既有 6 处逐字相同直读模式（行 2855/2894/2947/3052/3099/3495，同变量同回退）——新增端点同模式登记而非规避门禁语义；.venv 软链 ls-tree 计 0（未入库、.gitignore 覆盖），属环境锚定非门禁掩盖。",
    "测试不掩盖缺陷": "抽查关键用例均为实质故障注入/契约断言（>2000 字符命令列表截断+详情未截断+sha 绑定；跨进程签名密钥替换；409/400 契约；挤出场景）。唯一真实『测试掩盖缺陷』案例——首提交前端 P1 判别冲突（测试 mock 通过、真实服务器必锁门）——被 R1 独立审查抓出并在 e09fde130 修复，流程闭环有效。"
  },
  "conflicts_resolved": [],
  "focused_gates": [
    "tests/unit/test_escalation_m1_trust.py（存储层红→绿 49 passed，提交信息留痕）",
    "tests/test_escalation_m1_web.py（web 层红→绿）",
    "vitest EscalationCenter（门控/边界/409/挤出 6 tests；全套 590 passed）+ tsc --noEmit",
    "scripts/ci_gate.sh 全链路 exit 0：ruff/pyright ratchet new=0、env-pin PASS、xdist 全量 13847 passed"
  ],
  "main_sha_after": "父会话合并后回填（建议 git merge --no-ff m1-escalation-trust，保留单独 revert 归因；合并后 main 上复跑 escalation focused gate + tier0 冒烟）",
  "branch_disposition": "父会话按 lane 契约处置（建议 merged 后删除分支与 worktree）",
  "verify_receipt_id": "PASS 后由父会话按 EVO-20261106-7782d438 签发（scripts/issue_verify_receipt.py --apply，base-sha 以合并时 main 为准）",
  "notes": [
    "委派『data/review_admission/ 下 4 份 full_test 报告』表述与磁盘事实不符：PASS 裁决按设计不落报告文件（该目录 37 REVISE + 2 UNAVAILABLE，0 PASS；review_host_admission 仅 import rejected_receipt）。PASS 链权威证据为父会话审计事件，本审查已逐条核验为真，不影响裁决。",
    "验证凭证两处笔误（非阻断）：① R3 标签『candidate a4c534d7』实为 R2 的 candidate sha，R3 真实 sha=ad1fa92f（审计核对）；② baseline 登记 reason 引用的 data/review_admission/subagent_a7971b7afcdd-full_test.md 从未存在（PASS 不落文件），其对应 PASS 本身真实（13:53:22 审计事件）。建议合并后小步勘误。",
    "委派称『4 commit』实为 5 commit（含 82eac7541 docs-only 验证凭证，在 R4 冻结后落盘、不在 8 路径冻结面内，不影响 full_test 绑定），本回执已全量覆盖。",
    "main 前进风险已评估：merge-base f575846ff 之后 main 侧 4 提交与分支文件集零交集，merge-tree 对新旧两个 base 均零冲突；若父会话合并前 main 再前进，须重跑 merge-tree 预演并视交集决定是否窄复审。",
    "tier0 [4/5] 预检收集异常已在验证凭证如实登记（非阻断，全量超集权威绿）。"
  ]
}
```

## 审查过程留痕（只读命令逐条）
1. `git rev-parse main / m1-escalation-trust`、`git merge-base`、`git log --oneline main..branch`、worktree `git status --porcelain`（空）——分支卫生。
2. `git merge-tree --write-tree` 对 10fab6432 与 0bf687c2c 双预演（exit 0）；`comm -12` 两侧文件集（空交集）。
3. 逐 commit `git show`（9126e91e7/e09fde130/a844cafa7/c10ac276d 全量；82eac7541 docs）；终态文件复核（routes.py 503 文案、EscalationCenter.tsx 门控、list/get/pending_count 投影）。
4. 审查链一级证据：`data/event_logs/8ce6aa41-*.jsonl` 中 review_admission_qualified×3 + R1 rejected 报告 + 各轮 start 载荷（paths/target_name/previous_child_id 链）。
5. ci_gate 原始输出 `/tmp/ci_gate_out.dYD3vA` L496 逐字核对；baseline json registration_log 末条完整读取；.venv `git ls-tree -r` 计 0。
6. 设计书 §13 M1 批次范围核对（修复时间异常/失效 pending 复用/pending 独立分页/存储错误/长材料详情/过期投影 ↔ ESC-03/04/05/07/08/09 实现面一致）。

## s1_backfill（合并后回填，先例 cf7d2f4ba 模式）

- merge_commit: f7c09f06c5e0bc6b8fed489c222ca28b536913e0（--no-ff，可单独 revert）
- merged_at_base: 0bf687c2c78e464709ba3eebeedbb628c445c24e
- s1_result: PASS（人工合并临界区路径：合并审查 PASS + verify 凭证 lane-5af8407a:0bf687c2
  已按 EVO-20261106-7782d438 签发至 data/audit/verify_receipts.jsonl）
- 合并后 main 回归：escalation 面+gate 72 passed；tier0 341 passed/2 skipped
- 勘误（审查者 notes 指出）：
  1) 验证凭证"R3 PASS（candidate e09fde130）"标签笔误——R2=candidate a4c534d7…、
     R3=candidate ad1fa92f…、R4=candidate 24fec997…（本回执文件内已按正确顺序标注）
  2) baseline registration reason 引用的 R4 报告文件路径实际不存在——PASS 裁决按设计
     不落报告文件（目录仅 REVISE/UNAVAILABLE 落盘），权威证据为 append-only 审计事件，
     已由合并审查子代理独立核验为真
