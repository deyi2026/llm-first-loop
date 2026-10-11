---
method_id: preflight-lock-skew-check-before-booting-recently-changed-plugin-stack-ea028a6e3ce5
name: preflight-lock-skew-check-before-booting-recently-changed-plugin-stack
description: 启动/引导一个刚改过依赖的 runtime/plugin 栈前，用包管理器 lockfile 做 version-skew 预检：对比 runtime 自身版本族与 lock 中同族包的钉定版本；发现旧线实体（如 dep 的 peerDependencies 写 '*'，被 resolver 解析到旧版并 hoist 遮蔽 runtime 自带 bundle）先用精确版本对齐再启动，而不是先启动失败、再沿 patch/bundle/目录布局逐层验尸。lock 是『谁把哪个版本装进来』的权威 provenance 记录；失败诊断时它也应是把根因搜索空间从全文件系统缩到一条解析记录的第一跳。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:136b8530-addf-4ead-941f-0a53520c54d8:247:e1f20a61f854f679030a
evidence_refs: learning:learn:7696777ea061
created_at: 2026-10-11T19:48:12.031135+08:00
updated_at: 2026-10-11T19:48:12.031135+08:00
---
## Trigger
任务为启动/引导一个 runtime 或插件栈，且其 profile/workspace 依赖刚被改动（lockfile/package.json/node_modules mtime ≈ 当前会话，或本会话刚执行过 install）；或启动已失败、要回答『这个不兼容的旧版本包是谁装进来的』。

## Discriminator
当时已可见：runtime 自身版本（CLI --version / 全局 package.json）与 profile 的 pnpm-lock.yaml 存在且 mtime 等于本次 install 时间。此时 grep lock 即可发现：同一包族（runtime 自家 plugin/peer 包）被钉在与 runtime 不同的版本线（runtime 0.2.x vs 钉定 0.1.x），且引入者的 peerDependencies 写 '*'——'*' 的含义是 resolver 自选版本，不是『保证兼容』。

## Short path
- 预检 runtime 版本族（一条命令），并看 profile lock/package.json mtime 判断依赖是否刚变过。
- 若刚变过：先 grep lockfile 中 runtime 包族的钉定版本，而不是盲启动。
- 发现同族 skew（旧线实体将遮蔽 runtime bundle 版本）：按精确版本安装对齐（不带 caret，不走豁免），再启动。
- 若已启动失败：第一跳读 lockfile 找『谁解析出了这个版本』（顺着含 '*' peerDep 的 dep），不先枚举 patch 文件、bundle 清单、symlink 布局。
- 拿到 pid 存活 + 端口监听 + 日志无 startup failed 即停止。

## Stop conditions
- 启动已验证：进程存活、预期端口监听、日志无 'startup failed' / 'did not activate'。
- lock 预检显示同族包全部钉在 runtime 版本线上：直接启动，无需对齐。
- skew 包不属于 runtime 包族（无关旧版工具包）：不追查，正常启动。

## Verification
- 对齐安装后重读 lockfile，确认同族包已钉到 runtime 版本线。
- 启动后用 pid/端口/日志三重证据确认，而非仅凭启动命令回执（后台回执可能是 0 行输出的空壳）。
- 如实报告残余降级（如其他仍不兼容而被禁用的插件），不把部分成功说成全部正常。

## Counterexamples
- lock 早于上次成功启动、依赖未变：直接启动，预检是浪费轮次。
- runtime 不按 peer 版本做门禁禁用插件，或本地 hoist 无法遮蔽 runtime 自带 bundle：版本 skew 无害，不必先对齐。
- 首次启动、无 lock 无 baseline 可比：启动本身就是发现步骤，无从预判 skew。
- 新装 dep 的 peerDependencies 是固定/兼容范围版本且已解析到 runtime 同线：无 '*' 风险，不触发本方法。
