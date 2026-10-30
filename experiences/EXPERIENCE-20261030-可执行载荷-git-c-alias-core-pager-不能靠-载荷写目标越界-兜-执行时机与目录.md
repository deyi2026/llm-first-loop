---
title: "可执行载荷（git -c alias.*/core.pager）不能靠\"载荷写目标越界\"兜：执行时机与目录不可静态确定"
scenario: "命令闸拦 git -c alias.*/core.pager 注入时，若只按\"载荷写目标是否越界\"判定，相对路径载荷会被放行"
root_cause: ""
solution: 把 alias.*/core.pager 识别为可执行载荷，按 implicit_write_target 整体拒（不依赖载荷内容可定位），解析时保留 -c 的 key 以区分可执行配置与普通配置
evidence: 探针 reports/probe_r6b.py：git -c alias.log='!rm -rf ./x' log 等 4 条变体全部 blocked(implicit_write_target)；判定层 191 passed
tags: [command-guard, write-scope, git, threat-model]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T22:57:02.289873+08:00"
updated_at: "2026-10-30T22:57:02.289873+08:00"
---

**场景**：命令闸要拦"可执行载荷"注入（`git -c alias.log='!rm -rf ./x'`、`git -c core.pager='sh -c "…"'`）。

**根因**：若只按"载荷的写目标是否越界"判定 ⇒ **相对路径载荷**（`'!rm -rf ./x'`，恰在 scope 内）会放行。但 alias/pager 的真实威胁不是写目标位置，而是**执行时机与工作目录不可静态确定**（alias 绑定在**任意读子命令**上：log/status/… 都会触发）。

**解法**：把这类配置识别为**可执行载荷**并按"写目标不可静态定位"整体拒（`implicit_write_target`），不依赖载荷内容能否定位。判定上需要保留 `-c` 注入的 **key**（`alias.*` / `core.pager` 与普通配置 `user.name` 语义不同）⇒ 解析函数须返回 (key, value) 而非只返回 value。

**验证**：探针 `git -c alias.log='!rm -rf ./x' log` / `git -c 'alias.log=!rm -rf ./x' log` / `git -c core.pager='sh -c "rm -rf ./x"' log` 均被拦（implicit_write_target）；`git -c user.name=x log` 仍放行。

**边界**：拒的粒度是"该配置项"，不是"整个 git 命令" ⇒ 正常运维命令（设 user.name 等）不受影响。同源推广：任何"注入可被解释为命令"的配置项都应按可执行载荷处理。

**关联**：第六轮独立审查 P1-3；评审给的越界示例当时已被前轮修掉，真实漏口是**相对路径变体** —— 再次印证「上轮报障向量必须先在当前 HEAD 实测」。