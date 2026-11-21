---
method_id: frozen-pass-binds-snapshot-recheck-pinned-ref-before-reporting-6cf757d9a655
name: frozen-pass-binds-snapshot-recheck-pinned-ref-before-reporting
description: 材料冻结式异步审查的终态 PASS 只绑定启动瞬间冻结的快照哈希，不自动等于『覆盖任务钉住的 live ref』；而这类环境存在会推进 ref 的外部写入者（本集任务书自证：prior SHA review 因 HEAD 前进作废）。因此在把 PASS 报告为覆盖某个精确 SHA 之前，补一次只读回读（rev-parse+porcelain）闭合最后一个未知量『当前 ref 是否仍等于钉住值』：一致才归因收口；漂移则旧 PASS 无效，按新 ref 重审。它与『start↔terminal 回执 candidate_sha256 逐字节核对』互补：后者证明 reviewer 审的是冻结材料，本方法证明冻结材料仍是当前事实。回读只服务归因这一个比特，不是对已审内容的重复确认。
aliases: 审查完才发现代码又改了, 审的是旧版本还是当前版本, 审查通过后提交又变了还作数吗, 审了个过时的提交白审了, 验收前再确认工作树没被动过
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:9d50aa4b-460d-44e4-bf33-37e59c4cb684:42:31dbab6ab74ad4b909c6
evidence_refs: learning:learn:d003028bdc29
created_at: 2026-11-19T19:49:12.252180+08:00
updated_at: 2026-11-19T19:49:12.252180+08:00
---
## Trigger
对会变动的 live ref（如 git HEAD）发起材料冻结式异步独立审查/准入闸并收到终态 PASS，回执绑定的是 candidate_sha256 这类启动瞬间快照哈希而非 ref 本身的值，且任务验收要求 PASS 精确对应钉住的 ref 值。

## Discriminator
终态当时已可见的两条事实足以把归因问题缩成一次只读命令：①任务书声明 prior SHA review invalid——本环境确有会推进 HEAD 的写入者，快照与 live ref 会脱钩；②start 回执自述 candidate_sha256 是启动瞬间冻结的当前树的材料哈希、不是 git SHA。两者合起来：PASS 只证明 reviewer 看过冻结快照，『当前 HEAD 是否仍等于钉住 SHA』在终态时仍未解决，一次 rev-parse 即可闭合。

## Short path
- start 前一次性只读核验：rev-parse HEAD 与任务钉住的 SHA 逐字节全等且 porcelain 干净，确认冻结的就是用户要的树
- start 后按回执 waiting_protocol 有界轮询或绑定完成唤醒直到终态
- 终态先核对回执 candidate_sha256 与 start 回执逐字节一致（审的就是冻结材料）
- 在向用户报告『PASS 覆盖 pinned SHA』之前，一次只读 rev-parse+porcelain 确认 live ref 未漂移、树仍干净
- 一致→按精确 SHA 报告 PASS 并收口；漂移→不归因旧 PASS，报告漂移并在新 ref 上重新走闸

## Stop conditions
- 启动前/终态后两次 rev-parse 回显均与钉住 SHA 全等且树干净：PASS 可归因，报告后停止
- 终态回执 candidate_sha256 与 start 回执不一致：冻结材料被替换，资格作废，重走闸而非报告
- live ref 漂移或树变脏：旧 PASS 对新 ref 无效（同 prior SHA review invalid 情形），报告漂移并以新 ref 重审
- 终态非 PASS：不存在归因问题，直接转入失败/修复路径

## Verification
- 两次 rev-parse 回显与任务书 SHA 做逐字节比较（含长度），不靠前缀或记忆
- start 与 terminal 两张回执的 candidate_sha256 逐字节一致
- 最终报告只把 PASS 绑定到经终态后回读核验的那个精确 SHA，不绑定未核验的分支名或简称

## Counterexamples
- 终态回执本身已回显 verdict 时刻的 live ref/内容摘要且与钉住值一致：绑定已由权威回执建立，无需再读
- 被审材料按构造不可变（内联 patch 文本、冻结 blob、消息草稿）：不存在可漂移的 ref，终态后回读是空转
- 资格将在同进程立即被机械消费且闸按内容摘要 revalidate-on-use：漂移由闸兜底，无独立验收报告时可省去回读
