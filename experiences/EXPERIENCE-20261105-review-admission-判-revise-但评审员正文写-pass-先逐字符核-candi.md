---
title: review_admission 判 REVISE 但评审员正文写 PASS：先逐字符核 candidate_sha256 与 SHA 行
scenario: "Host 审核闸 review_admission(kind=full_test) 的 status 返回 qualification=REVISE、reason=review_verdict_incomplete_or_not_pass，但落盘 report 的 reviewer answer 尾行写着 \"VERDICT: PASS P0=0 P1=0 P2=4\"，看起来自相矛盾。"
root_cause: review_host_admission 的 PASS 判定要求答案尾行 SHA256 与 candidate_sha256 逐字符相等；评审员会凭记忆抄写 SHA，尾部字符出错。外加资格 revalidated_on_use 绑定切片外未跟踪文件摘要，活跃写入场景下资格会自行失效。
solution: |
  1) 读 data/review_admission/&lt;child_id&gt;-&lt;kind&gt;.md 头部 candidate_sha256 与 reviewer answer 尾行 SHA256，用脚本逐字符 diff（肉眼比对 64 位十六进制末尾极易看混）。本例候选 …8905ee70b6、评审员写 …8905e5f7b9，差 4 字符。2) SHA 不等 → fail-closed 正确行为，不是程序故障。3) 用 previous_child_id 走窄复审重取资格（材料含上次 findings，无需重启全量审查）。4) 另一条独立失效路径：签发后切片外未跟踪文件内容变化（如知识卡自动写入 data/methods/*）导致资格失效，报错文案为「不存在覆盖当前产物、目标及父会话的有效独立审查资格」——同样直接窄复审刷新，不要改代码。
  
  当前性验证：grep -n "sha_lines\[0\] == sha" src/llm_loop/tools/review_host_admission.py 应仍命中（本卡基于 2890 行附近）；若该门被改写则本卡判定依据需重新核对。
evidence: "data/review_admission/subagent_1196eeb37e6b-full_test.md 第11行 candidate_sha256=3ff50273…8905ee70b6、第58行评审员 SHA256=…8905e5f7b9；逐字符 diff 位置 59/60/61/63。src/llm_loop/tools/review_host_admission.py:2890 附近 sha_lines[0] == sha 门 与 :4180/4185 verdict/SHA 行契约。review_admission status 回执 qualification=REVISE reason=review_verdict_incomplete_or_not_pass。窄复审 subagent_a5c17e9a40f6 同 candidate_sha256 返回 PASS。"
tags: [review_admission, RULE-AI-28, 审核闸, fail-closed, sha256]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-05T17:45:27.859265+08:00"
updated_at: "2026-11-05T17:45:27.859265+08:00"
---

诊断顺序：status 报 REVISE 但报告正文 PASS → 取落盘 md 两处 SHA 做程序化 diff → 不等则窄复审（previous_child_id）重取；不要改代码、不要视为程序故障、也不要直接采信正文 PASS。另一失效路径同法处置：报错文案为「不存在覆盖…有效独立审查资格」时，多因审查期间切片外未跟踪文件（知识卡写入）变化，同样用窄复审刷新，成本约 2 分钟。

当前性验证：先 grep -n "sha_lines\[0\] == sha" src/llm_loop/tools/review_host_admission.py 确认该门仍存在（本卡基于该行 2890 附近）；再用 ls data/review_admission/*-full_test.md 取最新报告，脚本比对头部 candidate_sha256 与尾行 SHA256——不等即复现本失效模式。