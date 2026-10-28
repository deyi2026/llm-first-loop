---
method_id: probe-env-bound-params-from-ground-truth-not-convention-4a9076ca6f6c
name: probe-env-bound-params-from-ground-truth-not-convention
description: 首次调用会强校验环境绑定参数（workdir、绝对路径、数值上限）的工具前，若会话内尚无任何回执披露过真实取值，先用最小只读探针（pwd/ls、读 schema 区间）建立唯一真值，再发起调用；禁止用通用约定默认值（如 /workspace、默认时长）填充缺失参数。本例首调即因 workdir=/workspace 确定性失败，随后一次 pwd 直接得到真实仓库根；同族错误还有猜 wait 单次上限导致 300s 超界失败。核心机制：参数缺失=未解未知量，应由探针或已披露事实消解，而非约定猜测。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cfb48927-c4d8-44fb-9dd3-cd89bb5523c9:250:6bcdf6b9c8763680f9dd
evidence_refs: learning:learn:a876c032fcb7
created_at: 2026-10-19T00:52:19.144695+08:00
updated_at: 2026-10-19T00:52:19.144695+08:00
---
## Trigger
任务涉及部署/发布/门禁动作，需要首次调用带 workdir 或其他环境绑定参数、且参数会被工具强校验（无效即拒绝）的工具；此前没有任何回执、schema 默认值或环境文档披露过该参数的真实取值。

## Discriminator
被调工具的参数要求『有效目录』或声明了明确数值区间，而会话内已有回执（状态/审计输出）只含数值指标、不含任何绝对路径或边界值——即真实 workdir 是当前未解未知量，此时用约定默认值填充只会产生一次确定性失败，而一次 pwd 即可把它缩为唯一真值。

## Short path
- 先用只读身份探针（pwd && ls -d ~/*）解析真实项目根，一次解决『环境在哪』这一未知量
- git status/log 确认树状态、HEAD 与未提交改动范围
- 从规则/文档 SoT 消歧动作语义（如 publish=代码部署而非文章发表），据此推导闸集合与依赖顺序：干净树→代码审查闸→全量门禁→发布→generation 核验
- 按依赖序执行：收口提交（被 .gitignore 覆盖但历史已跟踪的工件用 -f 收口并注明先例）→ 以真实 workdir 启动审查准入 → 轮询 status 至 PASS
- 全量门禁放后台执行，用工具声明的单次 wait 上限（如 ≤120s）循环等待至终态，以 exit code 定结论
- publish/update 后核验 desired generation 已固化、服务收敛计划明确，向用户汇报剩余自动生效步骤

## Stop conditions
- workdir/上限等参数已由某次回执、schema 默认值或部署文档明确披露，可直接使用无需探针
- 工具接受相对路径或以调用方 cwd 为默认且不校验绝对值
- 真实路径已在本会话建立（pwd 已执行），后续同环境调用直接复用

## Verification
- 首个带 workdir 的参数化调用一次通过，无『不是有效目录』类参数错误
- 所有 wait/poll 的单次请求值落在工具声明区间内，无参数超界失败
- 审查准入冻结的产物指纹与已收口提交后的树一致（未在收口前启动闸）

## Counterexamples
- 系统提示或部署文档已写明规范 workdir（如容器内固定路径）——直接使用约定值即可，先探针反而多余
- 工具以调用方 cwd 为默认且不校验绝对路径——无需显式 workdir，本方法不适用
- 纯只读、幂等、无参数校验的探测调用，猜错代价≈0——不强制先探（但 pwd 类探针通常仍更便宜）
