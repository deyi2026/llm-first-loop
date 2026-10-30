---
title: 取值型选项必须覆盖短选项粘连形态：token 精确匹配会取错操作数而放行越界写
scenario: 命令闸实现取值型选项时，短选项粘连形态（tar -cvf FILE）导致取错操作数、越界写目标被放行
root_cause: ""
solution: 取值型选项解析单独处理粘连簇（末位取下一 token / 内嵌取剩余 / 无下一 token 则不可静态定位），并按命令族定义规则而非全局通用解析器
evidence: 探针 reports/probe_r6.py：tar -cvf /outside/x.tar a → blocked(write_target_outside_scope)，tar -czf /outside/x.tar.gz a → blocked；判定层 191 passed
tags: [command-guard, write-scope, parser, option-cluster]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T22:56:50.129439+08:00"
updated_at: "2026-10-30T22:56:50.129439+08:00"
---

**场景**：命令闸实现"取值型选项"（选项 + 取值，如 `tar -f FILE`、`tar --file=FILE`）时，判定器用 token 精确匹配（`-f` 恰为某 token）。

**根因**：短选项可**粘连**成单 token（`tar -cvf FILE`），精确匹配认不出 ⇒ 取值落空后回退到位置参数逻辑，而粘连形态里 `positional[0]` **就是**该取值 ⇒ 取错操作数 ⇒ 真实越界写目标被放行（`tar -cvf /outside/x.tar a` 曾放行）。

**解法**：取值型选项的解析要**单独处理粘连簇**：
- 簇末位是该选项（`-cvf`）⇒ 取**下一个 token**；
- 簇内嵌该选项（`-cvfARCHIVE`）⇒ 取簇内剩余部分；
- 末位是该选项但无下一 token ⇒ 取值不可静态定位（拒）。
另需处理**老式无横线写法**（`tar cf ARCHIVE`：首词是开关串，取第 2 个位置参数）。

**验证**：探针 `tar -cvf /outside/x.tar a` / `tar -czf /outside/x.tar.gz a` 均被拦且理由 write_target_outside_scope。

**边界**：不同命令的粘连簇语义不同（`tar` 的 f 取值、perl 的 i 是就地编辑开关而非取值）。通用做法是**按命令族**定义粘连规则，不要写全局通用的"粘连解析器"。

**关联**：第六轮独立审查 P1-1；同源模式见「载体选项区必须与内层命令语义分离」。