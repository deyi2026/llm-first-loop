---
method_id: pointer-zero-markers-pivot-to-store-content-scan-ca6f7af53941
name: pointer-zero-markers-pivot-to-store-content-scan
description: 用户/上游以精确指针（URL 带 session/记录 id、记录 id、路径）指定目标内容所在记录时，先把指针解析成具体记录，再对目标内容的不可碰撞标记（专有编号、原因码、小节号、复合 token）做全量计数：全 0 即指针与载体错位，这是指纹证据而非『目标不存在』——浅层/指针 miss 被写成『没写』正是上一轮的越证错误。正确下一跳是在同一 store 内对其他候选记录批量跑同一组标记计数定位真载体，取出内容后到磁盘验证其引用的 artifact（行号/mtime/配套痕迹）。指针有效性由内容命中数裁决，不由指针来源的权威性裁决。
aliases: 用户给的 session 链接内容对不上, url 里的 session id 找不到目标内容, 回执其实在另一条会话里, 跨会话按关键词定位真实记录, 指针指向的记录没有命中标记, 别把没检索到当成没写
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:6e7b4358-a1b8-4e23-a99c-931d6e86bee2:587:db0525ee68bef49ccada
evidence_refs: learning:learn:5ecec2b0931c
created_at: 2026-10-29T07:32:27.772036+08:00
updated_at: 2026-10-29T07:32:27.772036+08:00
---
## Trigger
用户或上游以精确指针（带 session/记录 id 的 URL、记录 id、文件路径）声称目标内容在某记录中，需据此核验存在性或提取内容；或指针/浅层检索 miss 后正要下『不存在/没写』的结论。

## Discriminator
指针解析出的记录内，目标内容的不可碰撞标记全量计数是否为 0，且抽查个别命中确属无关。全 0 ⇒ 指针与载体错位，未知量从『目标是否存在』转为『哪份记录才是载体』；非零 ⇒ 指针有效，直接在记录内定位。

## Short path
- 沿指针的物理线索解析到具体记录：URL 端口 lsof→PID→其打开的 lock/数据文件路径→store 目录→记录文件。
- 对该记录全量计数目标标记（复合 token/编号/原因码），抽查可疑命中确认是否无关。
- 全 0 ⇒ 指针降级为线索：对同 store 其他候选记录（按体量/mtime 排序）批量跑同一组标记计数。
- 命中记录 ⇒ 定位具体消息/条目区间，取出目标内容及其引用的下游 artifact 路径。
- 到磁盘验证 artifact（行号、mtime、配套产物），输出指针记录 vs 命中记录的计数对照表。

## Stop conditions
- 指针记录内标记计数非零且抽查确认相关：指针有效，停止 store 扫描，直接在记录内提取。
- 已在磁盘验证目标内容存在，且指针错位证据已用计数对照表化。
- store 全部候选计数均 0 且目标属外部系统职责：转外部权威来源，停止本地扫描。

## Verification
- 重跑计数命令，核对指针记录与命中记录的计数对照（如全 0 vs 非零命中组）。
- 磁盘上目标 artifact 的行号/mtime/配套痕迹与命中记录内引用一致。
- 用于判 0 的标记确为不可碰撞 token，通用词的个别命中已抽查确认无关。

## Counterexamples
- 指针记录内标记计数非零：指针有效，跨 store 扫描纯属浪费。
- 标记是通用词（如 navigate、status）：计数会假阳假阴，0 不能证明指针错位，须换复合 token 再判。
- 记录读取被截断或流式（coverage 标 partial）：0 可能是覆盖不全而非指针错位，属覆盖率判别场景。
- 目标从未持久化到任何本地 store（纯外部系统状态）：全 store 0 是真信号，应查外部来源而非继续扫。
