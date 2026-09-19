---
method_id: gate-named-symbol-provenance-first-c98d1d0291f0
name: gate-named-symbol-provenance-first
description: 门禁/校验脚本报『文件X缺字面符号Y』且X当前无Y时，错误信息本身已给出符号级 provenance edge：应先用『全仓 grep 找Y的现行位置 + git log -S 判从未存在/近期被删』一次性定性假红或真回归，再做跨环境复现或相邻事实批量取证。本集该 decisive grep 排在第8步，且第5步把多未知量捆进一条含 bashism 的复合命令导致一次工具失败；按短路径可省约2-3次调用并更早钉死『检查器停在旧契约的预存假红』。另含退出码测量纪律：经管道取 $? 会读到 head/tail 的码。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:010fcc8e-3ba8-4948-9ae5-66a30cc8ea6e:704:cadc9017cc896bd687e0
evidence_refs: learning:learn:8e0eac9d3da8
created_at: 2026-09-17T15:12:19.484004+00:00
updated_at: 2026-09-17T15:12:19.484004+00:00
---
## Trigger
校验/lint/门禁失败信息点名了缺失的字面符号（编号/键/锚点）与目标文件路径；对该文件 grep 零命中；需要区分『真回归』与『检查器契约漂移导致的假红』。

## Discriminator
错误信息同时给出『缺失符号字面量+目标文件路径』，加上该文件当前 grep 零命中（摩擦发生前两条事实均已可见）——假设空间立刻缩为三分支：从未存在/已迁移他处/近期被删，各由一条命令（repo-wide git grep、git log -S）裁决，无需先做跨 worktree 复现或多提交批量取证。

## Short path
- 运行门禁取原始错误，确认其点名字面符号与目标文件（未知量：真回归还是契约漂移？）
- 对该文件及全源码树 grep 该符号：命中现行位置（如新装配模块）→契约已迁移、检查器锚点停滞；全仓零命中→进下一步
- git log -S 符号 -- 目标文件（或跨代表提交 git grep -c）：零历史=从未存在→预存假红；命中删除提交=真回归，下一跳即该提交
- 对照仍被维护的同步测试/消费方断言确认活契约锚点，提出修法：重指检查器锚点或直接委托测试判定，消灭双契约漂移
- 停止并报告根因分类与修法；跨环境/跨分支复现仅在 git 历史含糊时补做

## Stop conditions
- 符号现行位置被活跃代码与同步测试引用，且旧路径跨提交零命中→定性预存假红，停止取证
- git -S 命中删除该符号的提交→切换为回归排查分支，本方法终止
- 失败信息不含具体符号/文件粒度→无 provenance edge 可循，本方法不适用

## Verification
- 运行现行契约对应的同步单测作为活契约证据（绿=契约确实已演进到新锚点）
- 测门禁退出码时不经管道或使用 PIPESTATUS，避免读到 head/tail 的退出码（本集曾因此误报 exit=0，后自纠为真红）
- 结论附两条可复现命令输出：符号现居路径、旧路径跨提交零命中

## Counterexamples
- git -S 显示符号近期从目标文件被删除——这是真回归而非检查器漂移，应追删除提交修代码，而不是改检查器
- 符号在目标文件中确实存在但门禁仍红——多为检查器 ROOT/CWD/worktree 路径解析错误，应查路径常量而非契约漂移
- 失败仅为聚合性『校验失败』、无符号与文件粒度——无 provenance edge 可循，需先提高日志详细度再做判断
