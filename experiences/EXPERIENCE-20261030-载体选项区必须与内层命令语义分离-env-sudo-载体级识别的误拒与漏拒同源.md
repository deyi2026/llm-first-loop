---
title: 载体选项区必须与内层命令语义分离：env/sudo 载体级识别的误拒与漏拒同源
scenario: 命令闸实现中载体命令（env/sudo/nohup）的选项区与内层命令的操作数必须分开识别，否则同时产生误拒与漏拒
root_cause: ""
solution: 用 _carrier_split 返回的内层命令起点切出载体自身选项区（args 去掉 rest 的前缀），所有载体级语义识别（chdir 选项、环境变量赋值、选项型载荷）只在该区内做
evidence: 探针 reports/probe_r6.py：env grep -C 2 pat / env ls GIT_CONFIG_COUNT=1 放行，env -C /outside touch x 被拦；判定层 191 passed；棘轮门 40 passed
tags: [command-guard, write-scope, parser, false-positive, false-negative]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T22:56:40.561571+08:00"
updated_at: "2026-10-30T22:56:40.561571+08:00"
---

**场景**：为命令闸（写侧 scope 判定）实现命令族解析时，载体命令（`env` / `sudo` / `nohup`）自身有选项（`-C` chdir、`-D`），内层命令也有同名或形似的选项与赋值。

**根因**：解析器在载体 args 的**整段**上做语义识别（找 `-C` 找 `NAME=VALUE`），而语义只在**命令名之前**成立 ⇒
- 误拒（可用性损伤）：`env grep -C 2 pat` 的 `-C` 是 grep 的上下文行数，被误当 env 的 chdir；`env ls GIT_CONFIG_COUNT=1` 里那是 ls 的参数，被误当环境变量注入。
- 同源漏洞（安全损伤）：载体选项区本身被漏识别（真正越界的 `env -C /outside touch x` 反被放过）。

**解法**：`_carrier_split` 已知内层命令起点 ⇒ 载体选项区 = `args[: len(args) - len(rest)]`；所有载体级语义识别（chdir 选项、环境变量赋值、选项型载荷）只在该区内做，越过命令名即属内层命令语义。

**验证**：探针实测 `env grep -C 2 pat` / `env ls GIT_CONFIG_COUNT=1` 放行，`env -C /outside touch x` 仍被拦。

**边界**：依赖"能确定内层命令起点"。若载体语义允许命令名出现在任意位置（如 `env` 后可跟多个赋值+选项），需先严格切出赋值区与选项区再定位命令名，不能用"整段减去 rest"的粗切法。

**关联**：第六轮独立审查 P2-1 / P2-2；同源模式见「粘连短选项簇取错操作数」（tar -cvf）。