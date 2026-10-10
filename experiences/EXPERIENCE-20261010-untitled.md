---
title: 门禁回执必须自证环境指纹：跑错树幻影错误的根治
scenario: "冻结账本门禁（new=0 ratchet）在跑错树时对零 diff 文件报出大量幻影新错；门禁回执不含 root/HEAD/changed 来源字段，无法自证运行环境，取证耗时约 1 小时。类似地，后台门禁任务 exit=0 但 stdout 为空、产物为即删临时文件时，\"绿\"无法交叉验证。"
root_cause: ""
solution: "不改锁语义，只让回执自证身份：(1) 回执头打印 root 绝对路径+HEAD+账本 SHA vs 冻结值；(2) 打印 origin_head 与祖先校验是否实际执行；(3) 打印分析器版本 actual vs frozen；(4) changed 集合按 committed/uncommitted/untracked 分来源计数+清单。同时长任务输出一律重定向落盘文件并追加 EXIT 码，用落盘产物而非进程 stdout 做判定。当前性验证：跑 `.venv/bin/python scripts/check_static_diagnostics.py --tool ruff`，回执首行应为 `ratchet root=<仓库根>` 且含 HEAD/ledger_sha256/origin_head/analyzer/changed[committed|uncommitted|untracked] 行，末行 PASS。"
evidence: e1035891c（+31/-8）；/tmp/ci_gate_e1035891c.log EXIT=0 双 ratchet PASS 自证回执；job-1a1df8753d284fc2b71f；docs/RESULT-20261010-r9-static-ratchet-receipt-provenance.md
tags: [ci, receipt-provenance, fail-visible, ratchet, evidence]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-10T13:33:27.646285+08:00"
updated_at: "2026-10-10T13:33:27.646285+08:00"
---