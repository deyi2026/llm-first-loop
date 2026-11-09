---
method_id: collapse-append-only-versioned-ledger-to-latest-per-key-before-state-gat-c31715e337e5
name: collapse-append-only-versioned-ledger-to-latest-per-key-before-state-gates
description: 在按实体键版本化追加的 append-only 账本（本集 lanes.jsonl：每 lane 多行、update 走 expected_version CAS）上为新守卫/自检写『当前状态』谓词（如存在他人 live lane 即拦）时，逐行原始扫描会把已被新版本取代的历史行当成现态，造成永久误拦的 fail-closed 死锁。本集 P4 knowledge_flush 自检合并后才被 lane-selftest 的历史 open 行永久挡住，hotfix 66be7bc9e 改为只认每 lane 最新 version。正确顺序：先从写入方确认行语义（追加+version 递增=同键历史行共存），按 key 折叠到最新 version 再判定；同一谓词已有权威读者（lane_main_write_guard/hook）时对齐其读取口径；测试夹具必须含被取代历史行。
aliases: 旧 open 行把提交闸永久卡死, lanes.jsonl 多版本行误判 live, 追加账本历史行污染守卫判定, 事件日志算当前态先取每键最新, 新自检对齐既有 hook 读账本口径
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:8641d508-e8f7-4b4c-86d8-c698c6927b74:318:ca130e6f6dfb111e50a2
evidence_refs: learning:learn:73e31f3dad5c
created_at: 2026-11-09T22:23:46.946265+08:00
updated_at: 2026-11-09T22:23:46.946265+08:00
---
## Trigger
需要新写一个读共享 append-only 账本、做阻塞型当前状态判定的守卫/自检（如提交前检查他人 live lane），且写入方代码可见（版本 CAS/追加式 jsonl），或同一谓词已有既有权威消费者。

## Discriminator
写入方已展示同键多版本历史：update 使用 expected_version CAS、存储是追加式 jsonl——『任意一行命中即拦』不等于当前态；且既有 guard/hook 已实现同一 live-lane 谓词，其行加载语义就是现成参照。

## Short path
- 读账本写入方（store 类）确认行语义：追加 + version 递增 → 同键历史行共存，当前态≠任意单行
- 若同一谓词已有权威读者（既有 guard/hook），复用或对齐其行加载与折叠方式
- 按实体键取最新 version 折叠后再评估谓词；无法判定时按 fail-closed
- 测试夹具显式构造『open@v1 已被终态@v2 取代』的污染样例，验证不误拦
- 新守卫与权威读者在同一夹具上判定一致即停止

## Stop conditions
- 新守卫在含被取代历史行的账本上与权威读者判定一致
- 折叠规则（max version per key）与写入方 version 递增语义核对通过，且回归测试已固化原故障形态

## Verification
- 用 [open@v1→merged@v2] 历史账本跑新守卫：不拦且放行理由正确
- 同一账本跑既有权威 guard/hook，二者结论一致
- 回归测试覆盖『旧行未折叠会永久拦』的原故障

## Counterexamples
- 快照式账本（每次写覆盖/压缩为单行当前态）：逐行即现态，无需折叠
- 谓词本意是审计历史（『是否曾 open 过』）：必须扫全量行，折叠反而错误
- 无 version 字段的纯事件日志（open/close 事件对）：折叠应按事件配对或最后出现，不能套 max version
- 追加顺序不保证单调（乱序/回补）：『最后一行』不可靠，须显式 version 比较；无版本又无顺序时本方法不适用
