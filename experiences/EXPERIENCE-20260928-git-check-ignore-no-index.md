---
title: git check-ignore 假阴性：判定忽略必须用 --no-index 或交叉验证，路径形态不能替代
scenario: "用 `git check-ignore <dir>` 判定目录是否被 .gitignore 忽略时返回 rc=1（空输出），被误判为\"未忽略\"。本仓库实例：`.backup/`（`.gitignore:76` 已覆盖，但目录内有 3 个文件先于规则 12 天入库）。"
root_cause: "`check-ignore` 默认 consult index——路径本身被追踪、或其**目录含 tracked 内容**时，即使 gitignore 规则匹配也判\"非忽略\"（假阴性）。与路径形态无关：尾斜杠同样 rc=1；未跟踪子路径 rc=0、**已跟踪子路径 rc=1**（注：某前置评审版本曾称\"子路径 rc=0\"，经复核只对未跟踪路径成立，已修正）。同类推论：gitignore 规则晚于文件入库时，对已 tracked 文件无效——加规则 ≠ 清出，须配 `git rm --cached`。"
solution: ① 判定用 `git check-ignore -v --no-index <path>`（唯一与追踪状态无关的判据）；② 交叉验证 `git ls-files -o --exclude-standard`（未忽略集）与 `git ls-files -- <path>`（tracked/untracked 分界）；③ 注意 `git status --ignored` 只覆盖未跟踪内容，对 tracked 内容有盲区。
evidence: 本仓库 2026-09-28 命令矩阵（llm-first-loop-mirror）：`.backup` rc=1 / `.backup/` rc=1 / 未跟踪子路径 rc=0 / 已跟踪子路径 `.backup/pollution-20260828/README.md` rc=1 / `--no-index` 两者 rc=0 / `.venv` 对照 rc=0；`git blame` 2f35e47752(2026-09-09) vs 入库 5ad31ab7d(2026-08-28)；`git ls-files -- .backup` = 3 个 tracked；`git ls-files -o --exclude-standard | grep '^.backup/'` = 0。
tags: [git, gitignore, check-ignore, evidence-method, tooling]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-28T18:01:46.656884+08:00"
updated_at: "2026-09-28T18:03:30.000000+08:00"
---