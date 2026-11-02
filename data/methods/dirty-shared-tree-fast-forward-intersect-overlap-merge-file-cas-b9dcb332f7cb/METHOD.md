---
method_id: dirty-shared-tree-fast-forward-intersect-overlap-merge-file-cas-b9dcb332f7cb
name: dirty-shared-tree-fast-forward-intersect-overlap-merge-file-cas
description: 要在与他人共用的脏工作树上把本线合并/快进落进共享分支时，先只读重锚 HEAD 与完整脏清单，再机械求『本线引入文件 × 脏文件』交集：空交集走普通 CAS 快进；有交集则对每个重叠文件取两侧相对同一 base blob 的 diff，确认 hunk 不重叠后在 /tmp 用 merge-file 干跑，验证双向差集恰好互相等于对方那份补丁；随后对齐 index、把重叠文件写回合并结果、用带旧值校验的 update-ref 移 ref。全程不 stash、不 reset、不提交他人改动，事后核对脏清单不变、他人 WIP 逐字保留、本线文件干净。
aliases: 快进main会不会撞到别人没提交的改动, 两边改了同一个文件还能不能快进, 合并落地前先算重叠文件清单, hunk不重叠先在tmp干跑合并, 快进后别人工作区的改动还在吗
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:c2df336a-eb98-4baa-9220-9e80d36e4ee2:1707:176700c8a5161a575c92
evidence_refs: learning:learn:1d4f20d93785
created_at: 2026-10-31T21:45:44.903444+08:00
updated_at: 2026-10-31T21:45:44.903444+08:00
---
## Trigger
共享 git 工作树上存在另一并发线的未提交在制品（status 脏），同时需要把本线的合并/指针快进落进同一分支/ref，且脏文件集合与本次引入文件集合可能相交

## Discriminator
『合并引入文件清单』与『脏文件清单』的机械交集，动手前用两条只读命令即可取得。交集为空→普通快进即可；交集非空→比较重叠文件两侧相对同一 base blob 的 hunk 位置：同基线且 hunk 不重叠 ⇒ merge-file 必然干净、可安全合并写回；base blob 不同或 hunk 相交 ⇒ 不可安全快进，升级裁决或等对方先提交。

## Short path
- 只读重锚：rev-parse HEAD/目标 ref + status --porcelain 完整清单，确认上轮核验的基线未移动（移动则重跑安全核验）
- 求交集：本线合并提交的 diff 文件集 × 脏文件清单 → 得到重叠文件（通常为空或极少数），同时确认无已暂存项
- 重叠文件取证：git diff HEAD -- <f> 取对方未提交改动，git diff base..merge -- <f> 取本线改动；确认两侧 base blob 相同、hunk 行号区间不重叠
- 离仓干跑：把 base/本线/对方工作区三份拷到 /tmp，git merge-file --diff3 → 要求 rc=0 且冲突标记数为 0；再验证 merged 相对本线版的 diff 逐字等于对方补丁、相对对方版的 diff 逐字等于本线补丁（双向差集守恒）
- 落地：对引入文件 checkout <merge-commit> -- 对齐 index → 重叠文件写回 merged 结果 → update-ref 带 CAS（旧 SHA 不符即失败）
- 收尾核对：脏文件数前后一致；重叠文件相对新 HEAD 只剩对方那份未提交改动且与其原始补丁逐字对应；本线其余引入文件干净

## Stop conditions
- ref 已按预期移动且 CAS 旧值校验通过（期间无人抢先移 ref）
- 对方全部在制品逐字保留（相对新 HEAD 的 diff 与其原始补丁一致），本线引入文件全部干净
- 交集为空且 HEAD 未移动时，跳过取证/干跑分支，直接 CAS 快进

## Verification
- merge-file 退出码 0 且输出中冲突标记数为 0
- 双向差集守恒：merged 相对本线版本的 diff == 对方补丁；merged 相对对方工作区版本的 diff == 本线补丁
- 落地后脏文件数不变、对方每项在制品仍存在、本线引入文件 status 干净
- 干跑出现冲突标记或两侧 base blob 不一致 → 中止：不写回、不移 ref

## Counterexamples
- 两侧 hunk 相交或基于不同 base blob（对方改的是同一区域）→ 会出冲突标记，不可强行写回，需人工裁决或等对方先提交
- 工作树存在已暂存项 → 动 index 会覆盖他人暂存状态，先中止协调
- 交集为空 → 无需合并分支，普通快进即可，不要过度工程
- 对方在制品正被其进程持续写入（文件 mtime 频繁变化、清单还在增长）→ 即便 hunk 干净也应等其收口，避免合并进半成品
- 仓库门禁强制树干净才能动 ref → 本方法不适用，改为等待对方先落提交
