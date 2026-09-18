---
title: "提取类任务先验证\"是否已被上游完成\"再估工作量（StateBraid phase9→main 原语提取虚功避免）"
scenario: "评估\"从 research 分支提取原语入 main\"类任务时，以决策文档 + worktree 代码为依据估算工作量并推荐 PR 方案。"
root_cause: "提出方案时只确认了\"目的地目录存在\"（integration/ 含 contract.py、identity.py），没确认\"内容是否已完成移植\"，把已完成的上游工作误估为待做的提取工作量。决策文档的 KEEP 条款与落地提交是同一个 commit（2bf6d75），二者天然同步——读决策文档时本应顺藤摸到同一提交的文件清单。"
solution: "在估\"提取/移植\"工作量前，先做三步廉价核查：(1) `git log main -- <目标路径>` 看目标路径的落地提交；(2) `git show <决策提交> --stat` 决策文档与代码是否同 commit 落地；(3) 并排 diff 源原语与目标实现确认是移植而非独立重叠实现。本次结论：StateBraid phase9 的两个 KEEP 原语（TrustDomainDeriver、backend 兼容检查）已在 2bf6d75 与决策文档同 commit 完成移植（main 的 identity.py 是去 HTTP 化版本：ValueError 替代 ServiceControlError(503)，属正确库原语形态；活探针在 compat/llama_cpp + doctor.py 已有），main 测试 111 passed。B 选项无需执行。"
evidence: ""
tags: [statebraid, premise-check, extraction, git-workflow, decision-doc]
source: {}
status: active
created_at: "2026-09-11T02:45:35.030695+08:00"
updated_at: "2026-09-11T02:45:35.030695+08:00"
---