---
method_id: time-order-then-content-anchor-verify-apply-claims-not-receipts-ec9bb06188c3
name: time-order-then-content-anchor-verify-apply-claims-not-receipts
description: 对『补丁/复制/合并已应用到目标文件』类断言（来自上一轮、交接文档或刚拿到的命令回执），验证锚放在时序与内容层，不放回执/退出码层：先比目标文件 mtime 与源产物生成时间，目标更早即零内容读取直接证伪；再 grep 变更独有新增标记并核行数/块增量。已知假阳性机制：git apply 在仓库子目录运行会静默忽略 cwd 外路径并返回 0，『成功回执+退出码 0』不构成已变更证据。需预验补丁本体时，在仓库外 scratch 目录对干净副本真实 apply 后再验标记。
aliases: git apply 成功但文件没变, 补丁到底打上没有怎么核, 回执成功不等于文件改了, 上一轮说补丁已应用怎么验, 子目录跑 git apply 假成功
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:c2df336a-eb98-4baa-9220-9e80d36e4ee2:535:4ded2a2a6e4440316788
evidence_refs: learning:learn:150580b452bc
created_at: 2026-10-31T15:41:10.812553+08:00
updated_at: 2026-10-31T15:41:10.812553+08:00
---
## Trigger
即将声称、复述或依赖一个『补丁已应用/文件已复制合并/变更已写入目标』的断言；或刚执行 git apply、cp、patch 类文件变更命令拿到成功回执；或从交接继承上一轮『已应用』声称需要核真。

## Discriminator
目标文件 mtime 与源产物（补丁/源文件）生成时间的先后，加上变更独有内容标记的 grep 命中数：时序矛盾（目标早于源）可一步证伪；时序不矛盾时，只有『独有标记命中 >0 且行数增量与补丁规模一致』才算证实。回执文本与退出码无判别力（子目录 git apply 假成功）。

## Short path
- stat 目标文件与补丁/源文件，比较 mtime：目标早于源生成时间 ⇒ 判『未应用』，不重放命令
- 时序不矛盾或需正面证实：grep 补丁新增的 ≥2 个独有标记（新章节号/新键名/新常量）于目标文件
- 核对行数/块数增量是否与补丁 insertions/deletions 规模一致
- 两查通过才允许输出『已应用』；任一失败则定位机制（仓库子目录 cwd 陷阱、目录只读）而非盲目重试 apply
- 预验补丁本体：在仓库外临时目录对干净副本真实 apply，重复上述两查

## Stop conditions
- 时序或内容标记任一层证伪 → 停止重试/重放，转定位失败机制（cwd、写权限）
- 标记全命中且增量一致 → 验证完成，不追加『再确认』调用
- 确认目标目录只读 → 不再尝试就地 apply，改交用户执行或换可写位置

## Verification
- 补丁新增独有字符串在目标文件 grep 命中 ≥2 处
- wc -l 行数差与补丁 +/- 规模一致
- scratch 目录真实 apply 后同样两查通过（预验路径）

## Counterexamples
- 有并发写入者持续改写目标文件：mtime 晚于补丁不能证实已应用，必须依赖内容标记
- 声称的是已提交 commit 而非工作区文件：应改用 merge-base --is-ancestor / git log 验证，mtime 无意义
- 二进制或压缩产物无可 grep 标记与行数概念：改用 sha256/体积对比
