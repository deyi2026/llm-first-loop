---
method_id: identity-key-collision-check-before-canonicalizing-orphans-5f33c5eac17b
name: identity-key-collision-check-before-canonicalizing-orphans
description: 把命名不合规的记录文件收编进规范 store 前，先用文件名里已有的身份键（如日期前缀）对 store 做一次定向碰撞检查。规范命名通常可从 store 的 save()/glob 一眼读出（PREFIX-{date}-{slug}），而越轨文件往往已编码同一日期键：一次前缀列举即可把动作定性为'重复落盘，删重/挂链即可'或'确无对应，按规范新写'，避免先花力气撰写新记录、入库后才靠近重检测意外发现重复并被迫重新解释问题性质。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:230:7e91c2f26cee895b1926
evidence_refs: learning:learn:d6ee9fe59e83
created_at: 2026-09-24T08:36:05.333589+00:00
updated_at: 2026-09-24T08:36:05.333589+00:00
---
## Trigger
准备把不满足 store 命名规范（glob 不匹配）的知识/经验/记录 artifact 改写为规范记录并入库时；或任何'把越轨 artifact 吸收进按身份键命名的 store'的迁移/收编任务。

## Discriminator
store 的 save()/glob 显示规范名由可从越轨文件名直接提取的身份键（日期/键前缀）构成——此时一次 ls|grep <date> 的同键兄弟列举，即可把候选动作从'撰写一条新记录'缩到'删重/合并'或'确认独有后新写'。该事实在动手前已可见（规范命名样本与越轨文件名同屏出现），无需事后答案。

## Short path
- 一次 grep store 的 save()/glob，得到规范身份键构成（date+slug 等）
- 对每个越轨 artifact，从其文件名提取日期/身份键，前缀列举 store 中同键记录
- 命中同键兄弟→diff 内容覆盖度：覆盖则改为删除原件（git 留底）并在 canonical 上增补/挂链，不新建；不覆盖才另写
- 未命中→按 front matter 规范撰写新记录入库
- 写后域内检索验证每事件只有一条权威可达记录，glob 外无残留

## Stop conditions
- 每个 artifact 已定性：重复删除（有 git 历史可回溯）或新规范记录入库且检索可达
- 同键碰撞检查完成前不开始撰写新记录正文

## Verification
- 最终 store 内每个事件仅一条权威可达记录，命名规范外无越轨残留
- 删除路径在 git 历史中可回溯；supersedes/链接关系与内容覆盖 diff 一致

## Counterexamples
- store 规范名用保存时日期而越轨文件以事件日期命名：按事件日期查兄弟必然漏检，不能据此断言无重复，需升级为内容级近重检索
- store 用不透明哈希 ID 且 artifact 名不含身份键：廉价碰撞检查不可行，直接走 store 自带去重
- artifact 是全新独有内容：检查退化为一次多余列举，不改变后续动作
