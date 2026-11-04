---
title: "tsrs 0.18.0 实测已支持 -b/--build（任务前提\"不支持 -b\"被证伪）；且 tsrs/tc 的 tsbuildinfo 格式与退出码语义互不兼容"
scenario: "typecheck:shadow 上游跟踪定时任务（sched-f5536c3c）第2次核验，需要判定 tsrs 是否发布支持 -b/--build 的版本，并评估是否把 tsrs 接入 webui 构建链（构建链现用 tsc -b）"
root_cause: "沿用上游文档/任务正文的既有假设而未做二进制级实测；把\"文档提到 --build\"与\"锁定版本可用 --build\"混为一谈；同时把诊断一致性当作替换构建链的充分条件，遗漏增量缓存、退出码语义、开关可用性、协议覆盖四项。"
solution: "判定\"某工具是否支持某开关\"时，若任务正文自带前提（如\"锁定版本 0.18.0 不支持 -b\"），不得直接采信：以实际二进制的 --help/退出码/产物为唯一依据——0.18.0 的 `tsrs -b --help` 输出 \"Usage: tsrs -b [projects...] [options]\"，官方 v0.18.0 USAGE.md 亦写有 `tsrs -b --watch`，故\"不支持 -b\"为伪。评估能否替换构建链编译器时，除诊断一致性外必须实测四项：(1) 增量缓存文件格式（tsc 4814B 无 version 键 vs tsrs 15798B 带 version 键，写同一路径会互踩）；(2) 失败退出码（tsc=1 vs tsrs=2，构建脚本会原样透传）；(3) 被测开关在锁定版本是否真的可用（0.18.0 的 -b 拒绝 --fast TS5072，--fast preset 是 0.20.0 才引入）；(4) 现有 shadow/回归协议是否覆盖将被替换的那条命令（协议测 --noEmit vs -p，构建链用 -b，属未覆盖路径）。另注：脚本名 typecheck:fast 实为 tsrs -p tsconfig.json，未传 --fast。"
evidence: "npm view tsrs dist-tags → latest=0.21.0-ts7.1.0-beta（较上次核验的 0.18.0 已推进）；官方 v0.21.0 docs/USAGE.md 明示 \"tsrs -b --watch rebuild when files change, like tsc\" 与 \"--fast, --checkers and --singleThreaded work with --build\"；仓库锁定 0.18.0 实测 `tsrs -b --help` → \"Usage: tsrs -b [projects...] [options]\"、`tsrs -b` 对 TS2322 正确报错 exit=2 并写 tsbuildinfo（证伪任务前提\"0.18.0 不支持 -b\"）；/tmp 隔离副本对照实测 tsc -b 1.58s / tsrs -b 0.10s、TS2322 诊断归一化后 diff 为空、tsbuildinfo 4814B(无version) vs 15798B(有version)、错误退出码 tsc=1 vs tsrs=2、`tsrs -b --fast` 报 TS5072 Unknown build option；webui/.typecheck-shadow.jsonl 累计2行均 agree=true 且均0 error；webui/package.json 中 typecheck:fast 实为 \"tsrs -p tsconfig.json\"（未传 --fast），build 链实际命令为 tsc -b。"
tags: [tsrs, typecheck-shadow, build-chain, tool-claim-verification, sched-f5536c3c]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T12:46:35.197781+08:00"
updated_at: "2026-11-04T12:46:35.197781+08:00"
---