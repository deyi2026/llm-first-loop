---
method_id: rerun-blocked-op-via-receipt-prepared-assets-1616c1285a15
name: rerun-blocked-op-via-receipt-prepared-assets
description: 用户告知某此前被硬阻塞的已记录操作（发布/提交）已解除（如'手机号已绑'）并要求补跑时，先读该操作的阻塞回执：回执内含 blocker 证据、prepared_assets（脚本名/标题/标签）与 user_action_required 重跑指令，是重入的权威索引。据此在回执所在目录树按名定位脚本并按 phase 重跑，而不是先对 scripts/tools/bin 等无关代码树做关键词 grep、超时后再全局重搜。与 resume-continuation-via-named-provenance（极简'继续'指令+stop 文档/git delta）边界不同：本方法针对有回执记录的单次阻塞操作的重跑，判别物是回执的 prepared_assets 字段。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:210fc8d0-2403-4baa-b382-986c0da37761:240:3b866a29c9ca76d654e2
evidence_refs: learning:learn:ff0e94c5d4c4
created_at: 2026-10-14T00:07:19.409004+08:00
updated_at: 2026-10-14T00:07:19.409004+08:00
---
## Trigger
用户报告此前 hard-block 的已记录操作（发布/提交/部署）的阻塞条件已解除（绑手机号、开权限、解锁），要求补跑；或需要重跑任何有回执/经验卡记录的失败操作

## Discriminator
已读的经验卡是否按名引用了该操作的回执路径、且回执文件确认存在但尚未读取——存在这样一条未消费的命名 provenance edge 时，跨目录关键词发现是多余动作；回执本身会点名可重跑资产

## Short path
- 从经验卡/记录取回执确切路径（本集经验卡 evidence 已点名 receipts/…-juejin.json）→ 未知量：上次阻塞原因与重跑入口
- 读回执：确认 blocker（403 must bind phone）已被用户动作解除，取 prepared_assets 中脚本名单与 user_action_required 重跑指令
- 在回执所在目录树按名定位脚本（工作目录 ls/glob 即命中：_pub16_*.py 与回执同在 docs/promotion/），不必 grep 其他代码树
- 核对脚本头部常量（TITLE/MD/KEYS/PHASE）与当前任务一致后按 phase 重跑 fill→confirm→verify
- 公网回读标题+关键句验证，更新回执状态为已发布并落库

## Stop conditions
- 回执点名的重跑链路执行完毕且公网验证通过、新回执落库
- 回执被证伪：点名脚本不存在或管线已改名 → 此时才扩大到目录/代码搜索发现
- 用户目标是新文章而非同一篇：回执资产只作模板，不得直接重跑

## Verification
- 重跑后原阻塞响应不再出现（如 article_draft/create 不再返回 403 must bind phone，草稿创建成功）
- 公网回读：URL 200、标题命中、关键句 N/N 全中
- 新回执记录发布时间、平台 URL 与公网验证结果

## Counterexamples
- 全新操作无任何回执/记录：没有命名资产可循，宽发现是正当起点
- 要发布的是新文章：旧脚本硬编码标题/正文路径，直接重跑会发错内容，只能复制改参
- 回执严重过时（脚本迁移、平台交互改版）：按名定位失败或重跑即报错，应回经验库查最新配方而非执着旧回执
