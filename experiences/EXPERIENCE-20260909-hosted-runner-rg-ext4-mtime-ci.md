---
title: Hosted runner 镜像去预装 rg + ext4 mtime 粒度致 CI 稳定红（本地全绿的假回归）
scenario: GitHub Actions 门禁全红但本地全绿；多个无关 PR（含 8 行 fixture PR）失败相同
root_cause: ""
solution: 三步定责：1) gh pr checks + gh run view --log-failed 取失败测试清单；2) 用最小 diff PR 对照——若同样失败则查 main 自身 run 时间线（gh run list --branch main）；3) 绿→红切换点附近 diff 未触碰失败文件 → 归因 runner 镜像/环境（本次：镜像去 ripgrep + ext4 mtime 粒度）。修复=CI 装 ripgrep + mtime 粒度免疫（os.utime 显式推进），勿把宿主二进制依赖留给 hosted runner。
evidence: "gh run 34351739996（main@d59169f fail，同样 2 tests）/ 34362373227（PR#2 fail 同样）；本地干净全量 0 failed 对照"
tags: [github-actions, runner-image, ripgrep, mtime-granularity, ci-flaky, base-comparison, triage]
source: {}
status: active
created_at: "2026-09-09T22:22:27.786856+08:00"
updated_at: "2026-09-09T22:22:27.786856+08:00"
---

2026-09-09 22:20 定责：GitHub hosted runner 在 11:31→12:33（UTC）间更新镜像后不再预装 ripgrep，老测试 e9d40af 引入的 `subprocess(["rg",...])`（test_control_plane_closure.py:94）在 CI 稳定 FileNotFoundError；同批 interop_watch::test_wakeup_only_coordinate_and_rate_limited 因 ext4 mtime 粒度粗（同 tick 写入+poll 看不到变化）稳定 assert 0==1。本地（macOS/APFS + 装有 rg）1428 全绿=纯 CI 环境差异。鉴别路径：PR#2（8 行 fixture）同失败→基线问题→查 main 分支自身最近 CI run 时间线→11:31 green/12:33 red 且 d59169f 未触碰这两个文件→归因 runner 镜像。修复方向：CI workflow 装 ripgrep（保留 G8 扫描覆盖）+ 测试用 os.utime 显式推进 mtime 或 watcher 改比 size/content。教训：依赖宿主预装二进制（rg）或文件 mtime 粒度的测试在 hosted runner 上是时间炸弹，CI 门禁红时先取 --log-failed 看是哪类失败再动代码。