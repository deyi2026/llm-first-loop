---
method_id: derive-command-target-path-from-episode-receipts-not-recalled-memory-5abe4e517a0d
name: derive-command-target-path-from-episode-receipts-not-recalled-memory
description: 需要向某仓库/目录发起 git 或文件命令、而路径来自记忆或旧会话时，先查本集已有工具回执是否已展示同一 scope 的权威绝对路径（如 read_file 回执头的仓库根路径）；有则直接派生路径执行，不凭回忆拼路径。跨环境路径（容器 /home/... vs 宿主 /Users/...）尤其易错位。若已发生 'No such file or directory' 类确定性失败，不要枚举路径变体，而是对比失败路径与回执路径风格、从回执重新派生后一次重试，并用回执中对象存在性（commits/文件可见）验证指向正确 scope。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:1942:74ca36a58486f1338b27
evidence_refs: learning:learn:b211753f075d
created_at: 2026-10-14T19:53:32.639724+08:00
updated_at: 2026-10-14T19:53:32.639724+08:00
---
## Trigger
要执行路径型命令（git -C / 文件读写），目标标识符来自记忆或先前会话而非本集回执；或命令刚因 'No such file or directory'（退出码确定性失败，非 transient）被拒，正在选择下一个路径重试

## Discriminator
本集更早的工具回执已展示同一 scope 内 artifact 的权威绝对路径（如 read_file 回执头部的完整文件路径，其目录前缀即仓库根）——该事实在失败发生前就已可见，可唯一确定命令作用位置，无需回忆或枚举

## Short path
- 发起路径型命令前，扫一眼本集回执是否已含同 scope 的绝对路径；有则以它派生目标路径（未知量：命令的确切作用位置）
- 本集无此类回执时，用一次探测（pwd / git rev-parse --show-toplevel / 列目录）确定根，而不是猜路径或枚举变体
- 已遇 'No such file or directory'：对比失败路径与回执路径的前缀风格（/home vs /Users 等），判定为跨环境记忆错位，从回执重派路径后仅重试一次
- 验证：重试回执中引用对象（SHA、文件、目录内容）确实存在且符合预期
- 路径验证通过后立即回到原任务主线，不再纠缠路径问题

## Stop conditions
- 命令回执成功返回预期对象（commits/文件/状态），证明派生路径指向正确 scope
- 本集回执无 scope 路径、且一次探测已取得权威根路径

## Verification
- 失败路径前缀 ≠ 回执权威路径前缀 → 判定记忆错位而非仓库损坏/网络问题
- 重试命令回执中出现被引用的具体对象（如 commit SHA 列表、目标文件内容），确认路径与 scope 一致

## Counterexamples
- 本集从未触碰目标仓库、回执中无任何相关路径 → 本方法不适用，应走发现性探测而非回执派生
- 回执路径属于报告/镜像目录，与要核验的 commits 可能分属不同仓库 → 直接沿用会指错仓库，需先用对象存在性（git cat-file -e / merge-base）验证同库
- 用户显式给出另一路径且与回执冲突 → 以用户输入为准，不以回执覆盖
