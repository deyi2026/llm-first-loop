---
method_id: blob-history-membership-then-supersession-for-merge-adjudication-424780a39fe1
name: blob-history-membership-then-supersession-for-merge-adjudication
description: 批量分区（ahead/cherry/diffstat）之后仍剩一批 cherry + 的幸存分支/worktree 时，裁决不要止步于树级 diff——main 持续前进会让 diffstat 全是删减假象（几百文件、几万行 deletions 看似分支删了 main 的东西）。第一步用机械事实分流：对 HEAD 改动集每个文件 blob 查是否存在于 main 全历史对象库。全命中 ⇒ 内容已通过其他 sha 进入 main，再核对 main 同路径最后提交日期+subject 确认是『已并入后被修订/超越』而非分支新增；有未命中 ⇒ 真『main 从未有』内容。第二步对真独有者做 supersession 裁决：main 是否已有同职责继任实现（同路径更新的实现、继任设计引用）。被继任 ⇒ 打 refs/archive tag 归档后删除、不并入（并回会带回被取代实现和会与现行治理冲突的配置）；无继任 ⇒ 才进入 rebase+测试+merge gate。删除前对 staged/dirty 树各落一份 patch；main 已脱敏/有意移除的旧版严禁从旧树恢复。
aliases: 这批分支还有没有活价值, cherry 加号是真缺吗, 独有提交被 main 取代了还并吗, diffstat 全是删减是不是假象, 归档还是合并怎么选, 删树前怎么确认不丢东西
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:794:fcba84dbac4174b26948
evidence_refs: learning:learn:47fb9f7a0d67
created_at: 2026-11-05T16:53:58.321482+08:00
updated_at: 2026-11-05T16:53:58.321482+08:00
---
## Trigger
对一批与 main 分叉的旧分支/worktree 做并入 vs 删除裁决，结构分区已完成，且存在 cherry +（patch-id 不等价）或树级 diff 差异醒目的幸存者

## Discriminator
HEAD 改动文件的 blob 是否存在于 main 全历史（git rev-list --objects / cat-file --batch 可批量机械裁决）：命中把『机械不等价』直接判成『已等价或已被超越』，无需逐主题符号猜测；未命中者再以 main 侧同路径继任实现定『归档不并』还是『真需并』。警惕 blob 命中≠应保留：main 后来有意删除/脱敏过的内容（旧版含私网信息）恢复即事故。

## Short path
- 沿用批量分区：一个脚本取全部树的 ahead、cherry ±、diffstat、dirty 计数，产出排序总表
- 对 cherry_plus>0 的幸存者：列出相对 merge-base 改动文件的 blob，批量查 main 全历史成员资格
- blob 全命中 main ⇒ 判『已等价/被超越』：核对 main 同路径最后提交日期+subject 与分支主题关系（同 subject 且更新=已并入后被修订）
- 存在 main 从未有的 blob ⇒ 列出路径与主题，但不要立刻判『应并入』
- 对真独有内容查继任：main 当前树是否已有同职责替代实现或继任设计引用 ⇒ 是则 tag refs/archive/<名> 后删；否则才评估 rebase+复跑测试+merge gate
- 执行删除前：每棵 staged/dirty 树 git diff 落一份 patch 留底；含脱敏前旧版的文件显式标记为禁止恢复

## Stop conditions
- 每棵树的处置（直接删 / 归档后删 / 评估并入）都有 main 侧可引用事实支撑（blob 成员资格、同路径最后提交、继任实现文件）
- live 依赖树（现役 code_root 等）与被裁决集合已显式分离，批量结论不外溢到现役树

## Verification
- 抽样复核：cherry + 但 blob 全在 main 的树，main 同路径最后提交 subject 应与分支提交主题同源、内容为超集方向
- 判『归档不并』的真独有树，能在 main 当前树指出具体继任实现文件后再下结论
- 归档 ref 建立后用 git for-each-ref / rev-list 确认可达，再执行删除

## Counterexamples
- 分支独有内容是 main 仍缺的活跃功能且无继任实现：blob 检查只回答『main 有没有过』，不回答『该不该要』——此时归档等于丢功能，必须走合并评估
- main 历史曾有该 blob 但被有意移除（回退、安全/脱敏删除）：blob 命中会被误读成『内容已保留』，从旧树恢复反而带回被删除的敏感旧版
- 只裁决一两棵树时，搭批量 blob 检查脚本的开销超过直接读 diff，逐树核对更快
