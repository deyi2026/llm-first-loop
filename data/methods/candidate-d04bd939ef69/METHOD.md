---
method_id: candidate-d04bd939ef69
name: 本环境怎么搜（检索顺序与引用纪律）
description: 本工作区检索顺序与引用纪律：教训先查卡库再查 docs 散档；引用提醒前必读 data/schedule.json 现值并禁硬编码 sid；专名搜索降级先查已有签名卡而非重新发明。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:fe0e1465-7509-459e-8792-eaaf6d7269f5:936:7c215bb8773beb7965ce
created_at: 2026-10-12T21:15:42.598410+08:00
updated_at: 2026-10-12T21:15:42.598410+08:00
---
## Trigger
要在本工作区找"以前的教训/方法/规则"（回答用户、写文档、或建新卡前 R1 去重检索）；或要在任何文档、提醒消息、SOP 里引用某个定时提醒/班次。

## Discriminator
- 检索目标是经验/教训/方法卡 → 用本卡顺序纪律（先卡库后散档）。
- 只查代码符号 → 走 grep 纪律（`experience:EXPERIENCE-20260916-grep-search-files-token`），不走本卡。
- 用户问"某提醒/设置当前状态" → 归 `method:state-questions-read-persisted-record-not-implementation-bdc629a6cc3e`；本卡只管"写文档时防引用漂移"。
- bing 返回词典降级结果集 → 归 `method:rehead-search-query-on-dictionary-degradation-8da50263deb1`；本卡只在其上叠加"先查签名卡再动手"这一步。
- 跨通道检索中确定性失败要关闭通道 → 归 `method:close-channel-on-deterministic-self-describing-failure-36bd486e20c1`。

## Short path
1. 教训/经验检索：`search_records(kind=experience)` 与 `search_records(kind=method)` 两个池 → 未命中再查 `docs/` 散档与工作笔记 → 仍未命中才承认空白。顺序反了（先 docs 或靠记忆）会漏卡。
2. 提醒引用：先读 `data/schedule.json` 现值 → 用「班次名+触发时间」指称 → 禁止硬编码 sid（sid 会腐烂，班次+时间不会）。
3. 专名搜索返回词典/百科噪声：先 `search_records` 查 rehead 签名卡是否覆盖 → 命中按卡走，不重新发明。

## Stop conditions
- 卡库与 docs 都未命中 → 停止检索，如实记录"空白"，不编造。
- `data/schedule.json` 读取失败 → 停止引用该提醒，改述为"班次名+触发时间+当前无法核验现值"，不猜 sid。
- 已按签名卡方法重试 2 次仍降级 → 关闭该搜索通道（转 close-channel 卡）。

## Verification
1. 任选一条已知教训（如"尾注翻车"），卡库检索应能命中；只能靠记忆/翻笔记找到即为反例。
2. `python3 -c "import json;[print(s['sid'],s['message'][:20]) for s in json.load(open('data/schedule.json'))]"` 列出当前活跃提醒；文档中出现的 sid 不在清单中即为腐烂引用。
3. 建卡时 R1 检索日志（2026-10-12）：两池查"教训检索顺序"零命中，证明本卡填补真空白而非重复建卡。

## Counterexamples
- 反例（S5 引用漂移）：设计作者引用晚班 sid `sched-ffe3746a`，该 sid 已不存在（被其他会话重注为 `sched-2a53c151`）——硬编码 sid 导致文档引用腐烂。
- 反例（S2 教训漏检）：尾注翻车教训写在 `20261012-session-notes.md`，不在卡库，靠记忆才捞出——只查 docs 或只靠记忆都会漏。
- 反例（bing 降级）：query「胖东来施工现场 干净得像AI 热榜」被按首词"胖"降级，返回 6 条字典结果零新闻；直接换关键词重试而不查签名卡，会重复踩同一坑。
