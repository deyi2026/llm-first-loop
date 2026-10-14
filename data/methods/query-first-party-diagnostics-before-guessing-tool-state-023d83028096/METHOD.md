---
method_id: query-first-party-diagnostics-before-guessing-tool-state-023d83028096
name: query-first-party-diagnostics-before-guessing-tool-state
description: 验证已安装工具/包的运行态事实（凭据是否存在、登录态、配置/数据路径、健康状态）时，优先查找并调用该包自己暴露的一手检查面——package.json bin 指向的自带 CLI（doctor/status 类子命令）或包内 vendored README——让被验证对象给出权威答案。凭猜测的系统目录只能生成假设，不能支撑'不存在/未配置'类结论；也不要在编译/压缩后的 bundle 上做多轮 grep 挖路径字符串。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:dbb11178-e3d2-4816-96e3-05377a07ca5b:17:0cf6f2ad39e76aa8369b
evidence_refs: learning:learn:ba0acb957268
created_at: 2026-10-13T18:48:17.420068+08:00
updated_at: 2026-10-13T18:48:17.420068+08:00
---
## Trigger
任务需确认某个已安装工具/包的运行态（凭据、登录、配置路径、host/daemon 健康等），而安装回执本身不包含这些事实，需要额外验证。

## Discriminator
包目录内当时已可见一手检查面的机械信号：包根 ls 显示 bin.d.ts 与可执行的 bin.js，package.json 有 bin 入口；且首轮 grep -rl 的命中列表已包含包内 README.md/README.en.md（文档覆盖目标关键词）。即'包自己知道自己怎么被检查'的证据在手，答案应在文档/CLI 而非压缩产物中；同时此前对凭据缺失的判断只来自一个猜测目录的 ls，属弱推断。

## Short path
- 明确未知量：'该工具自己认为状态是否满足、它从哪里读凭据/配置？'
- 看包根 ls 与 package.json 的 bin 字段；若首轮 grep -rl 命中包内 README，先读该文档对应小节
- 直接运行自带诊断（doctor/status 类子命令，优先 --json），拿到确切路径与状态字段
- 需要运行时登录/额度等细节时再跑状态类子命令，用返回值替代此前基于猜测目录的断言
- 条件全部满足即停止，不追加确认

## Stop conditions
- 自带诊断已返回目标事实（确切路径、登录态、健康）且其版本号与已安装版本一致
- 包无任何一手检查面（无 bin 入口、文档无关键词命中）时，才降级为静态 grep 或系统约定路径排查

## Verification
- 诊断输出的 package/version 与落盘安装版本一致，排除旧二进制或旧文档
- 对诊断给出的确切路径做一次只读存在性核对，并显式撤销此前基于猜测目录得出的存在/不存在断言

## Counterexamples
- 包不可信或供应链风险高：运行其 bin 等于执行第三方代码，此时只静态阅读文档/源码，不执行
- 包无 CLI 且文档无命中，目标事实极简单（如某文件是否存在）：一条 ls/test 更短，先找诊断面反而绕路
- vendored 文档明显落后于安装版本（大版本不一致）：路径/字段以运行时诊断输出为准，文档只作交叉验证
