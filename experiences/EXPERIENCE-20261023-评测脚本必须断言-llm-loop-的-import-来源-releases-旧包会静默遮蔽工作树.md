---
title: 评测脚本必须断言 llm_loop 的 import 来源（.releases 旧包会静默遮蔽工作树）
scenario: "在 llm-first-loop-mirror 里跑评测/重判脚本：环境装的是 .releases/<sha>/src 下的**非 editable** 旧包；脚本若把仓库根算错（parents[2] 而非 parents[1]），sys.path 就会指向不存在的目录，import 静默落到旧包 → 新增的判据（redline_v2）不存在 → run_verdict 走\"未知判据 → fail-closed\" → **所有样本判不通过**，看起来像\"全挂\"或\"结论崩了\"。"
root_cause: "路径层级算错 + 非 editable 安装的旧包遮蔽工作树代码，且失败模式是\"全部 fail-closed\"而不是报错，症状与真实失败无法区分。"
solution: "脚本启动时断言 import 来源：`import llm_loop; assert str(Path(llm_loop.__file__).resolve()).startswith(str(_ROOT))`，不对就 SystemExit 并打印实际路径与期望前缀。rejudge.py 已按此实现（2026-10-23 14:56 实测：修前全部 0/31，修后 25/31）。"
evidence: "evidence://v1/7a1fa22ef38f61fc7a4689add2f65db70c5202f78608834afcb0dbcb7528aead（修前 rejudge 全部 0/31）对比 evidence://v1/5a1fa22ef38f61fc7a4689add2f65db70c5202f78608834afcb0dbcb7528aead 修后 25/31；代码见 evals/rule_redline_v1/rejudge.py 的 import 断言。"
tags: [eval, python-import, releases, 踩坑, 失败模式]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-23T14:58:43.613920+08:00"
updated_at: "2026-10-23T14:58:43.613920+08:00"
---