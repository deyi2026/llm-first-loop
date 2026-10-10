# RESULT-20261010 — R9 收尾：NoReturn 修复全量绿 + 门禁回执自证加固

日期: 2026-10-10 ｜ 批次: R9 收尾（f621fd56c → 全量门禁 → guard e1035891c）

## 结论
1. fix(r9) `task_budget_authority._deny` 注解如实化为 NoReturn（f621fd56c，1 文件 ±2 行）：全量 ci_gate 通过。
2. 门禁"回执自证"加固落地（e1035891c，+31/-8）：锁语义（new=0、touched=0、账本/版本冻结、祖先校验）不变，只补回执——跑错树/集合错配自此在回执首行暴露。

## 绿证据（诚实形态）
- fix(r9) 全量: job-7c7a65aba42c4127a2d0 done exit=0。**stdout 未被捕获（0 行，管道 tail/swallow 形态）**；pytest 全量产物为 mktemp 临时文件且成功后即删——全量部分唯一机器回执为 exit=0，无落盘产物交叉验证。此为 ci_gate.sh 输出管线的已知缺口，如实记录（本次重跑已改为落盘 /tmp/ci_gate_e1035891c.log + EXIT 行）。
- 静态部分本地复证（f621fd56c 树上）: ruff new=0/resolved=15；pyright new=0/resolved=13；touched=0；ledger_sha256 与冻结值一致（b7ed6806d661…）；origin_head 500ee8f3eff0 祖先校验 enforced=True；分析器版本 frozen（ruff 0.16.5 / pyright 1.1.411）。

## 事故与动机
2026-10-10 12:57 一次跑错树的门禁运行对冻结账本报出 24 条幻影新错；HEAD 零 diff 文件混入 changed 集合（报告内部 2 vs 5 不一致），回执无任何字段暴露实际 root/HEAD/changed 来源，取证约 1 小时。锁按设计工作（抓到的 NoReturn 是真缺陷），不放松阈值；缺口在回执不自证。

## guard e1035891c 修复内容（scripts/check_static_diagnostics.py）
1. 回执头: root 绝对路径 + HEAD[:12] + ledger_sha256[:12] vs 冻结值；
2. origin_head[:12] + ancestry_enforced 实况（此前仅缺席时才说话）；
3. 分析器版本 actual vs frozen 行；
4. changed 集合分来源（committed/uncommitted/untracked）计数 + 清单打印。

## 验证
- 修改文件账本零债务（ruff/pyright hits 均空），不触发 BLOCK CHANGED FILE。
- 新回执两模式实跑 PASS: ruff new=0/resolved=15；pyright new=0/resolved=13；回执头/origin/版本/分来源 changed 全部自证。
- e1035891c 全量重跑: job-1a1df8753d284fc2b71f **EXIT=0**，落盘日志 /tmp/ci_gate_e1035891c.log 交叉验证：双 ratchet PASS（HEAD=e1035891cc9d 自证、账本 SHA=冻结值、origin 祖先校验 enforced、版本 frozen）+ "✅ ci_gate 全链路通过"。
