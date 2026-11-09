---
method_id: post-rewrite-edit-verify-file-mode-against-git-baseline-91b42d6c0310
name: post-rewrite-edit-verify-file-mode-against-git-baseline
description: 整文件重写式编辑（edit_file 原子写）按 umask 重建文件，会静默改掉执行位（100755→100644，工作区甚至 600）并可能丢文件末尾换行；bash path 方式调用照常能跑，只有 ./path 直调、hook、依赖执行位的调用会静默失效，通常拖到独立审查 REVISE 才被拦下（本集真实发生，多耗一整轮修订）。而开局定向 git log 里往往已有同类『恢复执行位 P1』修复提交可预警。方法：编辑任何调用契约依赖文件元数据的版本库文件前，用 git ls-files -s 记基线 mode；编辑后一条 git diff --summary 自检，出现 mode 行或『No newline at end of file』即恢复并复验；push 前把远端 ls-tree 模式纳入验证。把审查员才能发现的一类 P1 压缩成编辑后的机械自检。
aliases: 改完脚本 ./ 跑不了, 编辑工具把 755 改成 644, 整文件重写丢权限位, git diff 出现 old mode new mode, hook 脚本权限被编辑改掉, push 前核对脚本可执行权限
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:178:2aa22936ad8c433070e0
evidence_refs: learning:learn:21e3effe34bc
created_at: 2026-11-10T00:30:16.350970+08:00
updated_at: 2026-11-10T00:30:16.350970+08:00
---
## Trigger
用整文件重写式编辑工具修改 git index 中 mode≠100644、且调用契约依赖该元数据的版本库文件（hook、以 ./path 直调的脚本、权限敏感文件）；或开局 git log 已出现『执行位丢失/恢复执行位』类修复提交——后者是本仓库编辑链路的常设预警信号。

## Discriminator
编辑发生前已知的两条事实：① 开局定向 git log 里已有同失败类的『恢复执行位（P1）』修复提交，证明本仓编辑工具链会丢执行位；② 目标脚本在 git index 中为 100755 且被 CI/hook 以执行位方式调用。二者合一即可把『普通文档编辑』判为『编辑后必须核对模式与尾换行』的高危编辑。

## Short path
- 开局读 git log 时，凡见『恢复执行位/丢执行位』类提交，即给本仓所有脚本/hook 编辑打上元数据风险标记
- 编辑前 git ls-files -s <path> 记下基线 mode（如 100755）
- 编辑后立即 git diff --summary <path>（辅看完整 diff 的尾换行标记）：未知量=模式与末尾换行是否保持
- 出现 old mode/new mode 行或 '\ No newline at end of file' → chmod +x、补换行，复验 diff 干净；同一提交内其它被重写编辑的脚本顺带查一遍
- push 前验证包含模式项：远端 git ls-tree HEAD <path> 与基线一致；冒烟走 ./scripts/... 直调而非只 bash scripts/...（后者会掩盖缺陷）

## Stop conditions
- diff --summary 无 mode 行（或 mode 变化即本次意图）且文件末尾换行保持
- 远端 ls-tree 显示的模式与编辑前基线一致

## Verification
- git ls-files -s 编辑前后 mode 一致；git diff 中无 'old mode/new mode' 行与 'No newline at end of file'
- 用执行位依赖的调用方式（./path 直调）做冒烟，确认未被 bash path 调用掩盖

## Counterexamples
- 编辑普通 .md/.py/.toml（100644，调用不依赖模式）——自检无信息量，跳过以免制造噪音
- 编辑工具为就地补丁式（sed -i / apply_patch，保留 inode 与模式）——该风险不存在
- 本次意图就是新增或移除执行位——mode diff 是目的而非回归，只需核对方向
- 未跟踪的新建脚本——无 git 基线可比，应在创建时显式 chmod 并 ls -l 确认
