---
title: git apply 在仓库子目录内会静默忽略路径并返回成功——校验必须在仓库外做并逐条 grep 新章节存在性
scenario: 交付「git apply 补丁」时，在生产仓（MIRROR）的子目录里跑 `git apply --check` / `git apply` 校验补丁。回执显示 CHECK-OK 与 APPLIED、退出码 0，但目标文件实际一字未改（后续逐条 grep 新章节命中数为 0 才暴露）。根因：git apply 以 cwd 为基准解析补丁路径，路径位于 cwd 之外时按 git 的 prefix 规则被忽略，命令仍返回成功。同一轮更早还有一次反向假阳性：声称「补丁已应用到工作区」，实为工作区根本不可写且 mtime/grep 双证伪。
root_cause: git apply 的路径解析以当前工作目录为基准；位于 cwd 之外的补丁路径被按 prefix 规则忽略，命令返回成功但不产生任何写入。同时「命令成功」与「产物已变更」两个判据被混为一谈。
solution: 1) 补丁校验必须在**仓库外**的临时目录做：mkdir /tmp/xxx/docs/design → cp 目标文件 → git apply --check → git apply → 逐条 grep 新章节存在性 + 对比行数；2) 在仓库内校验时必须先 `cd` 到补丁路径所对应的仓库根（如 /Users/<user>/lfl-workspace），因为 git apply 按 cwd 解析路径；3) 判定「已应用」的唯一标准是**内容侧证据**（新章节 grep 命中、行数增量），不是命令退出码或回执文本；4) 「git apply --check 通过」只证明可干净应用，不等于已写入——两者必须在结论里分开表述；5) 同名补丁存在多份时，先按 sha256 + 逐 hunk 比对判冲突，只留一个 canonical，其余移入 superseded/ 并在 README 标注作废。
evidence: "evidence://v1/2a8114add1c4aab3b1bc95660bd72c7c73f1fef1e9a679d1b2c07f987dee8dfc (仓库内 apply 假阳性：APPLIED 但 grep=0、行数仍 843/220) | evidence://v1/9c5f0d4e... 见 /tmp/lfl-verify-apply-1031 仓库外真实 apply：843→916、220→327，§11.8 与 M4 探针均命中 | evidence://v1/d9954ca4fbf97431e04a7868e0607104c4406536a646142e0191d10a3aa36c9d (工作区不可写 + mtime 早于补丁生成时间，证伪「已应用」声称)"
tags: [git-apply, patch-delivery, false-positive, verification-discipline, done-claim]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T15:36:11.795354+08:00"
updated_at: "2026-10-31T15:36:11.795354+08:00"
---