---
title: gh run watch 接管道后 WATCH_EXIT=0 是假阳性；判定 CI 必须看原始状态
scenario: 后台执行 `gh run watch $RUN_ID --exit-status | tail -3; echo WATCH_EXIT=$?` 判断 GitHub Actions CI 成败。第一次 run 明明 failure，WATCH_EXIT 却为 0，导致差点在 CI 失败时误报闭环。
root_cause: shell 管道默认只传递最后一个命令的退出码；且 ruff --fix 不应用 unsafe fixes，与 CI 裸 check 口径不一致。
solution: 1) 管道中判退出码必须 `set -o pipefail`（否则 $? 只取 tail 的）；2) 终局判定不用 watch 的退出码，改用无管道的 `gh run list --limit N` 直接看 status/conclusion 字段；3) 本地预检与 CI 门禁口径要一致：ruff 用 `--fix` 后仍需裸 `ruff check` 复跑（I001 等 unsafe fix 不会被 --fix 应用，两次 CI 正是栽在这）。
evidence: "CI failure 时 WATCH_EXIT=0 的实测输出（job-81375fb6660b4fc0ae3d，evidence://v1/8b81c95b854a24a5727ed5039d57f4a49b7dd9c0c6c91a713254ed63941ce0b 起）；加 pipefail 后同一命令 WATCH_EXIT=0 且 gh run list 独立确认 completed/success run 34673685704。"
tags: [ci, shell, pipefail, ruff, release-flow]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-12T12:46:00.694964+08:00"
updated_at: "2026-09-12T12:46:00.694964+08:00"
---