---
method_id: reconcile-existing-install-before-mutating-342e01936595
name: reconcile-existing-install-before-mutating
description: 对一台已有可用安装的机器执行同类变更（升级、重装、补缺失依赖）前，先读现有安装的直接痕迹——which 解析出的真实路径/符号链接目标、既有 store 目录版本标签、lockfile——用它们钉死本次变更的参数（安装位置、辅助工具大版本），而不是沿用包管理器默认值或从格式特征反推。默认目标与现有位置不一致时必须显式 pin（如 --prefix、精确版本号），避免装出双份并存、旧版继续生效，或新工具与既有 workspace 不兼容。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:136b8530-addf-4ead-941f-0a53520c54d8:161:479482ee1d58213d2ffb
evidence_refs: learning:learn:9be2040de091
created_at: 2026-10-11T19:42:14.574315+08:00
updated_at: 2026-10-11T19:42:14.574315+08:00
---
## Trigger
即将对已存在可用安装的工具/插件执行变更性操作（npm -g 升级、为既有 profile 安装缺失的构建工具等），且 which/PATH 显示现有二进制位于非默认位置

## Discriminator
变更启动前的回执已显示 `which dsh` -> ~/.local/dsh/bin/dsh：现有安装位于用户自定义目录而非任何标准 npm prefix。这一个事实即预示：不带显式 target 的全局安装无法假定落到同一位置。同型证据：既有 node_modules/pnpm-lock/store 目录是缺失辅助工具（pnpm）真实版本的直接痕迹，优于 lockfileVersion+allowBuilds 的格式特征推断

## Short path
- 读 which 并解析符号链接，得到现有安装真实根目录；未知量：新版本必须落到哪才不产生双份？
- 查包管理器默认 target（npm config get prefix）并与真实根目录比对；未知量：默认安装是否命中同一位置？
- 不一致则带显式 pin 执行（npm install -g --prefix <现有根目录>）；一致才用默认
- 若还需补缺失辅助工具，先读既有痕迹（store 目录版本标签、lockfile 所在 workspace）钉死大版本再装；未知量：哪个版本与现有 store/node_modules 兼容？
- 验证 which 仍解析到同一路径、版本达到目标、默认 prefix 未被写入；满足即停

## Stop conditions
- 默认 target 与现有根目录一致且无需额外 pin，按标准流程执行
- 变更后 which 解析到原路径且版本为目标值，默认 prefix 处无新副本

## Verification
- readlink/which 对比：变更前后二进制真实路径一致
- <bin> --version 输出目标版本
- ls 默认 prefix 的 node_modules/<pkg> 不存在，确认未产生第二份安装

## Counterexamples
- 全新机器、无既有安装：没有任何现有痕迹可读，直接用包管理器默认流程，本方法不适用
- 现有二进制本就装在默认 prefix 内（which 落在 prefix 之下）：默认安装即正确，额外 pin 是无意义摩擦
- 用户明确要求迁移到标准位置、或现有安装已知损坏需重建：此时不应 pin 回旧位置，故意变更目标才是正确动作
