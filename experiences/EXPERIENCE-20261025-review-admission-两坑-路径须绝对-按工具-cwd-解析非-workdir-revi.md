---
title: review_admission 两坑：路径须绝对（按工具 cwd 解析非 workdir）；reviewer 本地化结论行 fail-closed 时同材料重启闸一次
scenario: review_admission(kind=article_publish) 从 lfl-workspace（非主仓库、非 git）送审头条发布闸
root_cause: ""
solution: 路径全绝对；遇 review_verdict_incomplete_or_not_pass 先读 review_tail：若 reviewer 实际结论 PASS 仅格式不合规，同冻结材料重启闸一次；仍不 PASS 才回稿修订
evidence: 两次 start 回执（subagent_3395ad1a03dc fail-closed REVISE + review_tail 含「结论：PASS」；subagent_ca83d10be478 PASS，candidate_sha256 两次一致 a52c68f4…）；receipts/daily39-admission.json note 字段全程留痕
tags: [promotion, review_admission, 发布闸]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-25T21:07:38.942078+08:00"
updated_at: "2026-10-25T21:07:38.942078+08:00"
---

d39 发表闸两坑连发：①manuscript_path 传相对路径（docs/promotion/xxx.md，workdir=lfl-workspace）被拒「review_material_not_a_file」——工具按**自身进程 cwd**（主仓库）解析 path，不相对 workdir 参数；manuscript_path 与 artifact_paths 全部传绝对路径后受理。②首次闸 reviewer 结论实为「结论：PASS P0=0 P1=0 P2=3 SHA256 正确」但结论行是中文本地化写法，未走 `VERDICT: PASS`/`P0=x P1=x P2=x`/`SHA256:` 三行契约，工具 fail-closed 记 REVISE（reason=review_verdict_incomplete_or_not_pass）。处置：**同冻结材料重新 start 一次闸（新 child），第二次规范输出 PASS**；不要人工解读 review_tail 放行（闸门存在意义即防此）。两坑合计耗时约 4 分钟。当前性验证：grep -n 'review_material_not_a_file' src/llm_loop/tools/review_host_admission.py 确认 _file_fingerprint 按 Path(path).expanduser() 解析；grep -n 'review_verdict_incomplete_or_not_pass' 同文件确认三行契约 fail-closed 逻辑仍在。