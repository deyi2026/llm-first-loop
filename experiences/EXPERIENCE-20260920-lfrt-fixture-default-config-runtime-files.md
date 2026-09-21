---
title: lfrt 单测 fixture 禁止携带真实部署路径：DEFAULT_CONFIG 副本会经 runtime_files 直写线上文件
scenario: 为 lfrt v1.1 编写后端切换单测：stashed_backends.mlx 取 deepcopy(DEFAULT_CONFIG)，cmd_switch→_apply_restart→runtime_files 把 DEFAULT_CONFIG 里的真实 repo/系统路径当作部署目标写盘（fork-config.json、launchd 双 plist，LaunchAgents 为 symlink）。仅因内容恰好逐字节相同才未产生真实漂移。
root_cause: 测试 fixture 复用了含真实部署路径的 DEFAULT_CONFIG，且写盘函数会跟随解析路径执行；未先隔离 paths 键。
solution: 规则：凡是会按 config.paths 写盘的代码路径，其单测 fixture 必须把所有路径键重写到 tempfile 目录后再进入被测函数；DEFAULT_CONFIG/defaults 只能作为值来源，不能原样作为可执行配置。附带：仓库外 `git diff --stat a b` 是 no-index 两文件对比，输出像 rename stat，不要误读为 git 历史状态。
evidence: "evidence://v1/9615736ac9930ac1bd66f1808d40fc6c06ec3b25ce6236964947994ca0876f0a (runtime git status 零漂移); evidence://v1/89737f733d310c2ab25b4ead1935eda002a88ded861ef6ffffc84d4986eec59c (测试 fixture 隔离修复)"
tags: [testing, test-isolation, lfrt, runtime, live-adjacent-paths, git-noindex]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-20T20:25:31.448252+08:00"
updated_at: "2026-09-20T20:25:31.448252+08:00"
---

runtime/test_lfrt.py 的 LlamaBackendTest 曾用 deepcopy(DEFAULT_CONFIG) 作为 stashed mlx 配置参与 switch 流程：runtime_files() 会解析其中的真实路径（repo plist、fork-config.json、LaunchAgents symlink 目标）并实际写盘。本次靠两个巧合零损伤：(a) LaunchAgents 的 mlx plist 是指向 repo 文件的 symlink，写入原子替换落在 repo 副本上；(b) DEFAULT_CONFIG 渲染结果与线上内容逐字节一致，git status 无 diff。验证方式：`git -C runtime status` 确认 fork-config.json 与 launchd/local.mlx.qwen8901.plist 未变更；随后把测试里 stash 的 5 个 paths 键全部改写到 temp 目录（test_switch_backend_bootouts_old_label_before_new_bootstrap）。规则：凡被测函数按 config.paths 落盘，测试 fixture 必须先把所有路径键指向临时目录，禁止裸用 DEFAULT_CONFIG 的真实路径。另外注意：在 git 仓库外运行 `git diff --stat f1 f2` 会退化为两文件对比（--no-index 语义），输出形如 rename stat，勿误判为仓库漂移。