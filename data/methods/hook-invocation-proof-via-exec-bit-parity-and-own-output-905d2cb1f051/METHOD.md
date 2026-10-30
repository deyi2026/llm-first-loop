---
method_id: hook-invocation-proof-via-exec-bit-parity-and-own-output-905d2cb1f051
name: hook-invocation-proof-via-exec-bit-parity-and-own-output
description: 复核『钩子已验证通过』类结论时，第一未知量是钩子是否真被 git 调用过，而不是其判定逻辑对不对。无执行位的钩子会被 git 静默跳过：外层命令 exit=0 既可能是『判定通过』也可能是『根本没调用』；直接用 bash 跑脚本又绕过执行位前置，两者都不构成调用证据。方法：先比对 ls -l 工作区 mode 与 git ls-files -s / HEAD（如 0600 vs 100755 ⇒ 必然被跳过，旧验证结论作废），补齐执行位后以『钩子自身输出行出现』为唯一阳性判据重测；传输/配置层先报错的路径（如 pushurl helper abort）不会触发钩子，不能当钩子探针用。
aliases: pre-push 钩子没生效, 钩子被静默跳过, exit 0 但钩子没跑, git hook 不触发怎么排查, 钩子验证假阳性
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f02d0f78-2dee-4e98-8056-26c7c3042ab0:50:3b7ead08c5b5c1ec6c00
evidence_refs: learning:learn:84cb26213b57
created_at: 2026-10-29T23:35:08.374916+08:00
updated_at: 2026-10-29T23:35:08.374916+08:00
---
## Trigger
验证『git 是否真的执行某钩子（pre-push/pre-commit 等闸脚本）』时，尤其是要复核上一轮已下的『钩子通过/验证 OK』结论；或回执中只有外层 git 命令退出码、只有直接用解释器运行脚本的结果、或 ls -l 已显示工作区钩子文件缺执行位。

## Discriminator
两条当时即可见的事实：①工作区钩子文件 mode 与 index/HEAD 不一致（如 -rw------- vs 100755）——git 对无执行位钩子是静默跳过、不报错；②历史『通过』回执里从未出现钩子自身打印的输出行——外层 exit=0 无法区分『判定通过』与『未被调用』，直接 bash 跑脚本绕过执行位前置，同样不构成调用证据。

## Short path
- 审已有验证回执：是否含钩子自身输出（banner/日志行）？只有退出码或直接解释器运行 ⇒ 『git 调用路径已验证』不成立。
- 三方比对 mode：ls -l 工作区 vs git ls-files -s（index）vs HEAD；工作区缺执行位 ⇒ git 必然跳过钩子，此前所有外层测试结论作废。
- chmod 补齐执行位后跑一次最小 dry-run，唯一阳性判据是钩子自身输出行出现。
- 输出出现 ⇒ 调用已证实，再评估放行/拒绝是否正确；未出现 ⇒ 下一假设转向 hooksPath 指向或 hook 文件名匹配，而非继续换 push 参数探测。
- 若外层在钩子之前就失败（如 pushurl helper abort），记录该路径不触发钩子，不再当探针。

## Stop conditions
- 钩子自身输出出现在 git 命令回执中，且正/负场景判定与设计一致（该拒的拒、该放的放）即停止。
- 确认外层失败早于钩子执行（传输/配置层报错）时，停止用该路径测试钩子。

## Verification
- 成功验证的回执必须含钩子自己打印的行（如 [pre-push] …）；仅 exit=0 不算数。
- worktree/index/HEAD 三处 mode 一致（100755）作为机械前置核对。
- 负向场景同样要求看到钩子的拒绝输出，不得用 helper/传输层错误冒充钩子拒绝。

## Counterexamples
- 回执已含钩子自身 banner 输出：调用已证实，无需再查执行位或重测。
- Windows 或 core.filemode=false 环境：mode 比对无意义，判据退化为钩子输出是否出现。
- 脚本由 CI 或显式 bash 调用而非 git hook 机制：执行位不是前置条件，外层退出码即有效证据。
- 钩子设计为静默通过（无输出）：应临时加打印或用 GIT_TRACE 证明调用，而非把无输出当失败。
