---
method_id: user-relayed-silent-write-verify-via-consumer-probe-c3e4863a8491
name: user-relayed-silent-write-verify-via-consumer-probe
description: 沙箱写封禁迫使你把凭据/存储写入委托给用户终端执行；用户回传只有命令回显与干净提示符返回（无输出、无错误）时，按该命令的静默成功语义推定成功，但闭环必须由你完成：用读取同一存储的消费端只读探针（如 gh auth status 实读 keychain 并打印生效 scopes）验证目标增量是否出现，达标才执行此前被阻塞的动作（按已核验的规范形态）。动作回执主效果行已成功、尾随错误仅命名本地簿记副作用（如 refs/remotes/origin/main）且与已知沙箱写限制一致时，归因无害，用带外权威（ls-remote 直查远端）确认终态后再清理敏感中间物。不要追问用户"成功了吗"，也不要在被封禁环境里重试写入。
aliases: 用户跑完命令没输出怎么确认成功, keychain 更新后怎么验证 gh 生效, 静默命令无输出算成功吗, 委托用户写凭据后的下一步验证, push 后 update_ref 报错要不要紧, 远端推没推上以哪个查询为准
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:3044:6742a84831c6b522a517
evidence_refs: learning:learn:8901f306781c
created_at: 2026-11-11T07:37:27.221841+08:00
updated_at: 2026-11-11T07:37:27.221841+08:00
---
## Trigger
你因沙箱写封禁无法自己执行某条凭据/存储写入，已委托用户在其终端执行，用户回传的终端记录只有命令回显和无错误文本的提示符返回；以及随后执行被解锁的受保护动作（push/merge）时，回执主效果行成功但尾随一行命名本地簿记对象的 error

## Discriminator
命令的静默成功语义（security add-generic-password、git commit 类成功时本就无输出）+ 回传无任何错误文本 → 推定成功但未验证；且当时已存在一个消费端只读探针（gh auth status 直接读 keychain 打印 scopes，此前还显示过旧值），可把"用户说跑完了"缩成一次可查的判别事实：此前缺失的目标增量（workflow scope）是否出现

## Short path
- 解析用户回传：命令与委托一致、无任何错误输出 → 按静默成功语义推定写入完成；未知量：新凭据是否已进入消费链
- 运行消费端只读探针（gh auth status）：检查此前缺失的目标增量是否出现；出现才解锁被阻塞动作，仍缺失则带判据回到用户侧排查
- 按此前回执已核验的规范形态执行被阻塞动作（裸 git push origin <sha>:refs/heads/main），先消费待用的一次性审查资格
- 读动作回执：主效果行成功（远端 ref 更新行）而尾随 error 仅命名本地簿记 ref、且与已知沙箱写限制（主仓库 .git 不可写）一致 → 归因良性，不重跑、不深挖锁问题
- 用带外权威验证终态（git ls-remote 直查远端，不依赖被阻塞的本地跟踪 ref），确认后清理敏感中间物（token 文件 rm + ls 复核）并汇报

## Stop conditions
- 消费端探针仍缺目标增量 → 用户侧写入未兑现，停止后续动作，把探针输出作为判据交回用户
- 带外权威查询已确认目标终态 → 停止验证，进入清理与汇报
- 回执错误命中的是动作主目标（远端 ref 被拒、认证、连接层）→ 非良性簿记噪声，停止收口并排查真实失败

## Verification
- gh auth status 打印的 scopes 含此前缺失项（探针实读存储的结果，非用户转述）
- git ls-remote origin refs/heads/main 返回目标 sha（绕过本地 refs/remotes 的陈旧值）
- 敏感文件删除后 ls 复核返回 No such file or directory

## Counterexamples
- 用户回传含错误文本（如 SecKeychainItem 类报错）→ 非静默成功，错误文本本身才是下一步判别器，不能推定成功
- 消费端有缓存或需重启/重载才读新值（守护进程启动时加载配置）→ 探针不能反映本次写入，应请用户侧运行读取命令或按文档确认生效条件
- push 回执错误为 remote rejected / 403 / failed to push some refs → 主效果真失败，不得当作本地簿记噪声跳过
- 本地 ref/reflog 可信且可写的普通环境 → 直接查本地台账即可，无需坚持带外查询
