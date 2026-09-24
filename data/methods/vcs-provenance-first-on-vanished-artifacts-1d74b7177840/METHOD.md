---
method_id: vcs-provenance-first-on-vanished-artifacts-1d74b7177840
name: vcs-provenance-first-on-vanished-artifacts
description: 在受版本控制的工作区里，近期确证存在过的文件突然返回干净的『文件不存在』失败，且现场有并发活动证据（早前 status 显示这些文件为 untracked、同级构建产物如 __pycache__/pyc 的 mtime 是几分钟前、目录 mtime 刚变）时，把『文件去哪了』当作 VCS 溯源问题而非文件发现问题：先 git log --all 查最近提交，git show 确认承载分支与文件清单，再做任何全库搜索。并行会话提交 untracked 工作后清理工作区是最常见成因，此时内容只存在于 git 对象中，search_files 类工具结构性找不到；失败回执里『改用 search_files 定位』的通用建议应让位于现场因果证据。找到承载提交后先读其报告结论，识别未被验证的缺口，只做增量工作。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5e09cedf-9412-454e-b7a9-f0247530ef7c:302:1b75dac208536dc50435
evidence_refs: learning:learn:d795adbf2c9c
created_at: 2026-09-22T17:49:17.328388+00:00
updated_at: 2026-09-22T17:49:17.328388+00:00
---
## Trigger
已知路径返回确定性的 file-not-exist 失败（非瞬态错误/权限问题），且现场证据表明文件近期确实存在过：早前 git status 曾将其列为 untracked、目标目录或同级构建产物（pyc/缓存）的 mtime 为几分钟前、或已知存在并行会话/后台任务在操作同一工作区。

## Discriminator
摩擦点（转向全库搜索）之前已可见三条事实：① 早前 git status 显示这些文件以 untracked 状态存在过；② 现场定性命令已显示目录 mtime 刚变、__pycache__ mtime 为几分钟前（对应脚本几分钟前还被执行过）；③ 读失败是确定性『不存在』回执。三者共同把假设空间从『路径错/从未存在/被移动/被提交』缩到『刚被并行会话消费或提交』；在多分支 git 仓库中，能一步验证该假设的查询是 git log --all 的近期提交，而被提交到其他分支的内容只存在于 git 对象中，文件系统枚举原理上找不到。

## Short path
- 读失败后先做一次廉价现场定性：ls 目标目录（残留文件与 mtime）、git status/branch、构建产物时间戳——未知量：这是路径错、瞬态失败，还是『刚被外部移走』？
- 定性为『近期存在过又消失』且处于 git 仓库内时，直接 git log --all（可加路径过滤）查最近提交——未知量：是否有并行会话刚提交了这批文件？不被失败回执的通用搜索建议带偏。
- git show <commit> --stat 确认文件清单与所在分支，再 git show 直接读关键产物（报告/结论/脚本接口）——未知量：对方已完成到什么程度、哪些结论已闭合？
- 从已恢复结论中识别唯一未被验证的缺口（如观察性归因从未做干预验证），只对该缺口设计增量实验；需要运行则用 git show <commit>:<path> 恢复文件。
- 增量结果与已恢复结论逐条比对（确认/推翻/补充），验证后归档，不重复已完成工作。

## Stop conditions
- git log --all 在观察到的活动时间窗内找到触及缺失路径的近期提交：停止一切发现类搜索，转入读取提交内容与增量工作
- 全部分支历史均无触及记录且文件从未被提交：此时才扩大到文件系统搜索（.worktrees、/tmp、构建产物反查、向用户求证）
- 现场定性显示只是当前 checkout 分支不对或路径拼错：直接 checkout/修正路径，不做溯源搜索

## Verification
- 承载提交的 --stat 文件清单覆盖全部缺失路径，且提交时间落在 mtime 证据所示活动窗口内
- 恢复出的产物与早前观察一致（如 pyc 对应同名脚本、目录残留旧文件吻合）
- 自己的增量结论与已恢复报告显式对照并标明推翻/确认/补充（本例：7/8 miss 为查询侧、1/8 为系统侧，推翻『模型语义上限』归因）

## Counterexamples
- 文件从未进过 git（纯 untracked 被 git clean/rm 删除）：git log --all 必然查无结果，应走文件系统搜索/worktrees/tmp/向用户求证路线
- 读失败是瞬态超时或权限问题而非确定性不存在回执：应重试或查权限，而非追提交历史
- 无并发活动迹象且目录 mtime 陈旧：更可能是路径拼错或当前分支不含该文件，先核对路径与 checkout 状态
- 工作区不受版本控制（无 .git）：VCS 溯源不存在，目录级搜索才是正确第一跳
