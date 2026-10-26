---
title: 不要用 git checkout -- 撤销局部编辑错误：它丢弃该文件全部未提交改动
scenario: "我在改 src/llm_loop/eval/verdicts.py 时，脚本把一行字符串插坏了（正则多行字符串被截断 → SyntaxError）。我为了撤销这一处错误，执行了 `git checkout -- src/llm_loop/eval/verdicts.py`，结果把该文件里**全部**未提交改动（约 4.3KB、10 处判据修改）一起丢弃，需重做。更糟的是：同时另一条并发工作线提交了工作区，把我已改好的其他文件收编进了 commit，`git status` 只剩 1 个未跟踪文件，**掩盖了\"我的改动丢了\"这个事实**，差点让我以为改动还在、继续在错误状态上开发。"
root_cause: ""
solution: "规则：(1) **绝不**用 `git checkout -- <file>` 撤销局部编辑错误——它丢弃该文件全部未提交改动。要撤销单处错误，用 `edit_file` 的精确替换（已校验 expected_snapshot_ref）或先 `cp file /tmp/backup` 再改；(2) 大批量改动前先 `cp` 备份到 /tmp，并把所有 patch 写成一个**带逐项断言**的脚本（每项 `if old not in s: 报错退出`），一次原子执行，避免中途失败留下半成品；(3) 改完立即 `cp` 再备份一次；(4) **并发工作区里 `git status` 干净不等于\"我的改动在\"**——必须用内容级校验（如 `git show HEAD:file | grep -c \"<我加的标记>\"`）确认自己的改动真的在 HEAD 里，因为别人的 commit 会把工作区改动一并收编；(5) 发现丢改动后不要用 git 历史\"恢复\"（那会带回旧版本），而是用记录重做 patch 脚本。"
evidence: "本轮实际发生：编辑 src/llm_loop/eval/verdicts.py 时脚本插坏了一行字符串，我用 `git checkout -- src/llm_loop/eval/verdicts.py` 想撤销那一处，结果把该文件全部未提交改动（约 4.3KB、10 项判据修改）一并丢弃，需重做 10 项 patch。同一时刻另一条并发工作线（2aedbdac1/09f9aa424/dbfa8e4bc）提交了工作区里我已改好的其他文件，因此 git status 只剩 1 个未跟踪文件，掩盖了\"我的改动丢了\"这个事实——是逐项 grep 计数才发现 HEAD 里 v5 改动计数为 0。当前性验证：跑 `grep -c \"v5 英文形态\" src/llm_loop/eval/verdicts.py` 应 >0；跑 `.venv/bin/python -m pytest tests/unit/test_eval_verdicts_v5.py -q` 应全过。"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-23T19:30:14.586923+08:00"
updated_at: "2026-10-23T19:30:14.586923+08:00"
supersedes: [EXPERIENCE-20261014-git-merge-冲突解决-checkout-ours-是整文件回退-会静默丢弃自动合并区的对侧改, EXPERIENCE-20260820-git-users]
---