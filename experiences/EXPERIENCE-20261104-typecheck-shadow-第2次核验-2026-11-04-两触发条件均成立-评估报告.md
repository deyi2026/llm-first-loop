---
title: "typecheck:shadow 第2次核验（2026-11-04）：两触发条件均成立（TS 7.0.2 stable + tsrs 0.21.0 支持 --build），shadow 仍不接入构建链"
scenario: "typecheck:shadow 定时跟踪（sched-f5536c3c，每2周×6次，工作目录 ~/Project/llm-first-loop-mirror）第2次执行（effect_id=schedule:sched-f5536c3c:2）"
root_cause: ""
solution: "两条件均成立故出评估报告；结论=暂不接入构建链，新增可核依据（build 模式未被 shadow 协议覆盖 / tsbuildinfo 格式不兼容 / 退出码语义不同 / 0.18.0 无 fast preset 且 -b 拒绝 --fast / 仓库仍为 tsc 5.9.3）"
evidence: "npm view typescript/tsrs dist-tags（2026-11-04）；tsrs v0.21.0 与 v0.18.0 官方 USAGE.md；webui/.typecheck-shadow.jsonl 共2行（均 agree=true、0 error）；/tmp 隔离副本实测 tsc -b 与 tsrs -b 行为对照"
tags: [sched-f5536c3c, typecheck-shadow, tsrs, typescript-7, recurring-task, build-chain-evaluation]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-04T12:50:00+08:00"
updated_at: "2026-11-04T12:50:00+08:00"
---

# typecheck:shadow 第2次核验评估报告（2026-11-04）

## 0. 触发条件核验（npm registry，只读）

| 条件 | 判定 | 依据（2026-11-04 回执） |
| --- | --- | --- |
| (1) typescript 已发布 7.x stable | **成立** | `npm view typescript dist-tags` → `latest=7.0.2`；发布时间 2026-07-08T15:55:18Z，无 -dev/-rc/-beta 后缀。`rc=7.0.1-rc`、`beta=7.1.0-beta`、`next=7.1.0-dev.20261103.1` 均为独立 tag，latest 未指向预发布 |
| (2) tsrs 已发布支持 -b/--build 的版本 | **成立** | `npm view tsrs dist-tags` → `latest=0.21.0-ts7.1.0-beta`（较第1次核验的 0.18.0 已推进）；官方 v0.21.0 `docs/USAGE.md` 明确 "`tsrs --watch -p .` and `tsrs -b --watch` rebuild when files change, like `tsc`"，且 "`--fast`, `--checkers` and `--singleThreaded` work with `--build`" |

**与第1次核验的差异**：tsrs latest 由 `0.18.0-ts7.1.0-dev.20260929` 变为 `0.21.0-ts7.1.0-beta`（0.20.0 / 0.20.1 / 0.21.0 三个新版本已发布）；typescript latest 仍为 7.0.2。

**任务前提更正（实测证伪）**：任务正文称"当前锁定版本 0.18.0-ts7.1.0-dev.20260929 不支持 -b"，实测**不成立**——仓库锁定的 0.18.0 二进制 `tsrs -b --help` 输出 `Usage: tsrs -b [projects...] [options]  See 'tsc -b --help' for options.`，且 `tsrs -b` 能正确报出类型错误并写出 tsbuildinfo。官方 v0.18.0 `docs/USAGE.md` 同样写有 `tsrs -b --watch` 与 "`--build` uses 4 per project"。故条件(2)在第1次核验时其实也已具备，只是当时未被识别。

## 1. shadow 累计数据汇总（webui/.typecheck-shadow.jsonl，gitignored，仅本地）

累计 2 条记录，**分歧 0 次**：

| # | 时间(UTC) | commit | agree | tsc | tsrs |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-21T04:27:21Z | 0193ace46 | true | exit=0, 1398ms, 0 err | exit=0, 130ms, 0 err |
| 2 | 2026-10-21T04:42:47Z | 8cebe9443 | true | exit=0, 1355ms, 0 err | exit=0, 140ms, 0 err |

- 速度：tsrs 约为 tsc 的 **1/10**（130–140ms vs 1355–1398ms），两次一致。
- 缺陷：两条记录**均为 0 error**，即"两边都没报错"的一致性，对错误捕获等价性的证明力弱；样本量 2，覆盖 2 个 commit，均为引入脚本本身附近的提交。
- 对比：第1次核验时为 1 条，本次新增 1 条（04:42:47Z），仍无分歧。

## 2. 补充实测（隔离副本，仓库零改动）

在 /tmp 的 webui 副本（node_modules 以符号链接指向仓库）对照实测：

| 项 | tsc（仓库锁定 5.9.3） | tsrs（仓库锁定 0.18.0） |
| --- | --- | --- |
| 干净树 `-b` 耗时 | real 1.58s | real 0.10s |
| 类型错误输出 | TS2322 ×2（位置、措辞一致） | 与 tsc **归一化后完全一致**（diff 为空） |
| 有错误时退出码 | 1 | **2** |
| tsbuildinfo | 4814 字节，无 `version` 键 | 15798 字节，含 `"version":"7.1.0-dev.20260930.4"` |
| `--fast` 与 `-b` 组合 | — | 0.18.0 报 `error TS5072: Unknown build option '--fast'`（exit 1） |
| 是否发出 .js | 否（noEmit 生效） | 否（noEmit 生效） |

附加事实：
- `webui/package.json` 中 `typecheck:fast` 实为 `tsrs -p tsconfig.json`，**并未传 `--fast`**；且 `--fast` preset 是 0.20.0 才引入的，0.18.0 完全没有。即当前 10× 加速来自 Rust 移植本身，不是 fast preset。
- 构建链实际命令是 `tsc -b`（`webui/scripts/build-with-source-binding.mjs`），而 shadow 协议比对的是 `tsc --noEmit` vs `tsrs -p tsconfig.json`——**shadow 从未覆盖 build 模式**。
- 仓库 `typescript` 依赖为 `^5.7.2`（实装 5.9.3），上游 7.0.2 stable 尚未进入本仓库。
- tsrs 0.18.0 默认每核一个 checker（最多 16），上游 0.21.0 默认回到 4 checker 对齐 Go 调度；官方声明 checker 数/文件序变化在已知用例下会改变诊断。

## 3. 评估结论：**暂不接入构建链**

理由（按证据强度排序）：
1. **协议覆盖缺口**：shadow 比的是 `--noEmit` vs `-p`，构建链用的是 `tsc -b`。把 tsrs 放进构建链等于启用一条从未被 shadow 校验过的路径（含增量缓存与 build 语义），无法用现有 2 条 agree=true 背书。
2. **增量缓存格式不兼容**：两者写同一个 `webui/tsconfig.tsbuildinfo`（tsc 4814B 无 version 键 / tsrs 15798B 带 version 键），交替运行互相覆盖、缓存语义不可信。
3. **退出码语义不同**：类型错误时 tsc=1、tsrs=2，构建脚本 `process.exit(result.status || 1)` 会把 2 透传给 CI，下游判定需同步调整。
4. **fast 路径当前不可用**：0.18.0 的 `-b` 拒绝 `--fast`，而仓库锁定的正是 0.18.0；`typecheck:fast` 脚本名与实际参数不符，接入前须先做版本升级决策。
5. **证据强度不足**：累计仅 2 条、均 0 error；本次仅补 1 类错误（TS2322）的对等证据，不足以覆盖错误捕获等价性。
6. **语义变更风险**：用 tsrs 替换 tsc 等于把 TS 7.1 语义引入当前 5.9.3 基线；正路是先采纳上游 typescript@7.0.2 stable，再让 tsrs 对标 7.0.2 语义。

### 建议的下一步（本次不执行）
- 升级 `typescript` 至 7.0.2 stable 后重建 shadow 基线（保持 tsc 侧为官方 stable，tsrs 侧选与其对齐的版本）。
- 把 shadow 协议扩到 build 模式（`tsrs -b` vs `tsc -b`），并给两侧**隔离的 tsbuildinfo 路径**，避免缓存互踩。
- 样本门槛：≥20 次且覆盖多类错误（TS2322 / TS2339 / TS2345 等）与含类型变更的提交，零分歧再评估。
- 接入方式应为"并行 shadow 步骤"，而非直接替换 `build-with-source-binding.mjs` 中的 `tsc -b`。

## 4. 复核建议
- 第3次及以后核验可跳过完整评估，只增量确认：shadow jsonl 新增记录与分歧、tsrs dist-tags 是否再推进、tsrs 锁定版本是否升级后重跑 shadow。
- 若 tsrs 升级到 0.21.0+，需重测 `-b` 与 `--fast` 组合、退出码、tsbuildinfo 格式三项，并重跑本报告第2节的对照表。
