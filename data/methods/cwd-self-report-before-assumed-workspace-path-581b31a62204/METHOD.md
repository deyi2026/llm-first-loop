---
method_id: cwd-self-report-before-assumed-workspace-path-581b31a62204
name: cwd-self-report-before-assumed-workspace-path
description: 续跑或新 shell 会话中未显式给出仓库路径时，不要假设 /workspace 等规范绝对路径，也不要在首次探测已失败后再补一次存在性确认。首条命令就用裸 pwd; ls 读取 shell 的权威自报（持久 harness 中常即项目根），再以 git rev-parse 验证。『cd X 2>/dev/null || cd ~ 后 pwd 显示回落目录』与『ls -la X|head 在 2>/dev/null 下退出码 0 但零输出』都已是 X 不存在的充分证据，重复探测不产生新信息。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7fa91553-3285-4608-a1bc-56326b46bea9:1111:5e76beb3017f8a29dddc
evidence_refs: learning:learn:6701130d591c
created_at: 2026-10-17T23:03:00.580435+08:00
updated_at: 2026-10-17T23:03:00.580435+08:00
---
## Trigger
极简续跑指令（如「继续收口」）或新 shell 会话开始，需要定位工作仓库但调用方未给路径，且即将假设一个规范绝对路径（/workspace、~/repo 等）

## Discriminator
shell 自身可一步自报默认 cwd（裸 pwd），无需任何假设；且首条条件 cd 的输出已含判别事实：pwd 打印的是回落目录即证明 cd X 失败、目标路径不存在，后续对该路径的 ls 复测是零信息动作（exit 0 + 空输出只是 stderr 被吞，不代表路径存在）

## Short path
- 首条命令即 `pwd; ls -la | head`，不附带假设路径的 cd——解决『当前权威工作目录在哪』这一未知量
- 若 pwd 处含 .git：直接 `git rev-parse --show-toplevel; git status; git diff --stat`，把『继续』量化为具体变更面
- 若 pwd 非仓库根：用上一条输出里可见的父目录结构或既有 evidence 点名路径做一次定向定位，而非枚举猜测多个规范路径
- 定位成功后立即进入任务本身（diff/测试/收口验证），不再出现任何路径类探测动作

## Stop conditions
- 在当前 cwd 运行 git rev-parse --show-toplevel 成功返回仓库根，后续 git 操作均在其上执行且输出一致
- 路径歧义消除后，不再对任何已被证伪的候选路径发起第二次存在性探测

## Verification
- 定位到的 cwd 下 git rev-parse --show-toplevel 与 git status 均成功且相互一致
- 回看轨迹：工作区定位动作总数 ≤1 条命令，无『猜路径→失败→复测同一路径』序列

## Counterexamples
- 封闭容器/CI 契约固定且 /workspace 真实存在时，直接使用契约路径即可，先 pwd 反而多余
- shell 默认 cwd 是家目录、仓库在别处时，裸 pwd 不足以定位，此时一次定向查找（ls 父目录/用点名路径）是必要的——本方法只禁止重复证明已证伪的猜测，不禁止查找
- 既有 evidence 或续跑回执已点名确切仓库路径时，应直接沿点名 provenance 走，连路径探测本身都可省略
