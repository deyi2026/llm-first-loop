---
method_id: two-axis-residency-adjudication-by-live-process-handles-before-release-s-86fc379a46ad
name: two-axis-residency-adjudication-by-live-process-handles-before-release-swap
description: 准备建议 publish/换 release 等替换代码来源的动作、且结论依赖持久化状态（账本/日志/store）去向时，不要从静态 config 默认值或目录布局推断。部署回执同时给出 code_root 与 runtime_root 两个不同根的事实，本身就把担忧拆成两个独立未知量：代码轴（活进程 env PYTHONPATH + 修复独有新符号 import 探针，即既有『重启前验证运行代码来源』方法的适用面）与数据轴（活进程 PID 的 lsof 打开句柄 + 活跃 mtime）。数据驻留由活进程实际打开的文件裁决，与代码副本解耦；据此修正或撤回此前未核实的断言，再给分步建议。
aliases: 发布后账本还在不在, 服务真正在写哪个data目录, 数据跟release走还是跟主仓库走, 发布前查数据落盘位置, 换版本丢不丢运行数据
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:73172f2a-c1f6-4868-9611-d4af1d463c48:3241:203be3dd6e2ca20dec26
evidence_refs: learning:learn:a8ce4231df75
created_at: 2026-11-03T23:58:39.668108+08:00
updated_at: 2026-11-03T23:58:39.668108+08:00
---
## Trigger
准备建议或执行会替换运行代码来源的动作（publish 新 release / restart 换副本），且结论依赖持久化状态的写入位置；或上一轮已对数据去向给出未经运行时验证的断言需要裁决。判别信号：部署/服务回执同时列出 code_root（如 .releases/<sha>）与 runtime_root（主仓库）两个不同的根。

## Discriminator
部署回执里 code_root ≠ runtime_root 这一当时已知事实：它证明代码来源与数据驻留是两条可独立验证的轴。数据轴的权威证据是活服务 PID 的 lsof 打开文件句柄（账本实际路径）与 mtime 活跃度；静态读 _DEFAULT_DATA_DIR 之类 copy-relative 默认值，在含 .releases/ 镜像的多副本工作区里无法裁决哪份生效。

## Short path
- 从部署/服务回执记下 code_root 与 runtime_root；两者不同 → 把『换 release 会不会丢状态』拆成代码轴与数据轴两个未知量。
- 代码轴：ps 定位活服务 PID，读其 env（PYTHONPATH / runtime root 变量）；用修复独有新符号在该副本做 import 探针——ModuleNotFoundError 即证明需 publish 才生效。
- 数据轴：lsof 该 PID 的打开文件 → 账本/日志实际写入根；用 mtime（分钟级更新）确认仍是活跃写入者。
- 若涉及新机制产物：检查该数据根下对应目录/文件是否存在——缺失应能被『机制未上线』解释，而非推断为丢失。
- 用两轴事实修正或撤回此前未核实断言，结论表述为『换 release 只动代码轴，数据轴不变（或相反，以 lsof 为准）』，再给分步建议。

## Stop conditions
- 代码副本被 env + import 探针唯一确定，且数据写入根被活进程打开句柄唯一确定——两条轴均已裁决即停。
- 新机制产物的存在/缺失与上线状态互相印证（未 publish → 产物应缺失；publish 后自检产物出现）。

## Verification
- import 探针结果与进程 env PYTHONPATH 指向同一副本（互相印证）。
- lsof 打开的账本路径 mtime 与当前时间同量级，证明是活写入者而非陈旧副本。
- publish 前后各查一次数据轴：写入根不变即证明换 release 不迁移数据。

## Counterexamples
- 服务未运行、无 PID 可 lsof：只能静态推导数据目录策略或做受控写探针，本方法不适用。
- 数据目录真由代码位置派生、无 runtime_root/workspace 覆盖（code_root==runtime_root 或数据随副本走）：换 release 确实会换数据根，必须先处理数据迁移/锚定，不能直接断言安全。
- 只问配置是否生效、不涉及替换代码来源：走链端点验证（进程启动时间 vs 配置 mtime + 行为产物），不必做两轴分解。
