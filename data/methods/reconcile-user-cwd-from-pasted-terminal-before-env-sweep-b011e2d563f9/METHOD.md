---
method_id: reconcile-user-cwd-from-pasted-terminal-before-env-sweep-b011e2d563f9
name: reconcile-user-cwd-from-pasted-terminal-before-env-sweep
description: 用户粘贴的终端报错本身就是 provenance：shell 提示符携带其 cwd 线索，相对路径 no such file 报错证明所缺工件是相对『用户 cwd』缺失（而非 PATH/拼写问题）。先把未知量收敛为『解析用户这一个目录』，确认该目录是否同时拥有可执行体与命令要读写的 cwd 相对状态（台账/数据/配置，含目标记录），再给出指向正确 checkout 的修正命令；只有提示符无 cwd 信息或目录名无法解析时才做全盘枚举。禁止在已有命名线索时先 find 全家目录枚举候选环境。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:236:4daf056089c9b706fabd
evidence_refs: learning:learn:45873f30115f
created_at: 2026-09-19T17:14:08.137256+00:00
updated_at: 2026-09-19T17:14:08.137256+00:00
---
## Trigger
用户粘贴终端会话，命令因相对路径失败（如 no such file or directory: .venv/bin/...），且粘贴的 shell 提示符显示了 cwd 目录名，与助手自身 pwd 不一致

## Discriminator
进入枚举前已见的两条事实：(1) 错误行是相对路径的 'no such file or directory'，证明该工件在用户 cwd 下缺失，未知量只是『用户 cwd 在哪』；(2) 提示符字符串里的目录名（如 worktree 名）直接给出用户 cwd 的 basename——候选空间从『全盘所有 .venv/仓库』缩为『解析这一个命名目录』

## Short path
- 从粘贴文本提取三要素：失败的相对路径（错误行）、用户 cwd basename（提示符）、助手自身 pwd；确认两者 cwd 不同
- 按该目录名做一次精确解析（find -name <目录名>），得到用户 cwd 绝对路径（如主仓下的 git worktree）
- 在解析出的目录检查：缺失工件是否存在（.venv 等）；命令将读写的 cwd 相对状态文件（台账/数据）是否存在；目标记录（目标 ID）在哪份状态里、当前状态是否允许该操作
- 定位同时拥有可执行体与含目标记录状态的 checkout，验证两者合一
- 给出指向该 checkout 的修正命令（cd + 原命令）与预期输出；人工登记通道的命令交回用户执行，停止

## Stop conditions
- 用户 cwd 已解析为绝对路径，且所缺工件与含目标记录的状态文件被证实同属一个 checkout，修正命令与预期输出已给出
- 提示符不含 cwd 信息或目录名解析失败 → 请用户执行 pwd，而不是扩大枚举
- 目标记录不存在、或其状态不允许该操作 → 停止并报告，而非换目录重试

## Verification
- 在推荐 cwd 下确认原失败的相对路径确实存在（如 .venv/bin/python 可执行）
- 确认目标记录存在于该 cwd 解析出的状态文件中，且状态与待执行操作兼容（如 accepted → 可 complete）
- 确认命令的状态路径解析基准（相对 cwd / 绝对 / env）与推荐 cwd 一致，不会落到另一份空台账
- 人工通道命令不代跑：交回用户并给出预期输出格式供回贴确认

## Counterexamples
- 用户提示符被定制为不含 cwd（如纯 $ 或极简主题）→ 提示符线索不存在，应直接请用户 pwd，本方法不可套用
- 错误是 command not found（PATH 问题）而非相对路径 no such file → cwd 对账与 venv 定位均无关
- 工具状态经绝对路径/env 解析、或目标记录就在 worktree 自己的台账里 → 『cd 回主仓根』是错误结论，必须跟随目标记录所在的那份状态而非固定目录
