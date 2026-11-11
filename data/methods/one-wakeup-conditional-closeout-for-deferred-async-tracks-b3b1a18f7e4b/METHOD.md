---
method_id: one-wakeup-conditional-closeout-for-deferred-async-tracks-b3b1a18f7e4b
name: one-wakeup-conditional-closeout-for-deferred-async-tracks
description: 会话收尾同时挂着多条未终态异步轨（deferred 重启 pending 于本 run 结束、在跑子审查、预授权 push）时，不做会话内轮询也不逐轨零散收口：把 deferred 回执自带的生效时机/终态判据/出口当收尾合同，注册单个定时唤醒，时长对齐最长轨 ETA，载荷写全每轨条件分支；向用户报告『已受理未生效+续办已排定』并显式不作完成宣称。收敛前的中间读数显示旧 generation/缺新字段判『未收敛』而非失败（回执由部署前进程生成）。
aliases: 重启要等本轮结束才动手怎么办, 下班前后台还有活没干完, 几个挂起任务一次唤醒全办完, 怎么告诉用户重启还没生效, 到点自动接着办的排程, 没查到 succeeded 别报完成
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d8d5d9ff-e288-4ad6-8855-48df99c3362e:1884:df8129cf93f8f11449d4
evidence_refs: learning:learn:26796ad2496e
created_at: 2026-11-11T23:57:04.869611+08:00
updated_at: 2026-11-11T23:57:04.869611+08:00
---
## Trigger
回合/会话收尾时同时存在多条未到终态的异步轨：至少一条受管动作回执显式 deferred_effect（pending=true，生效条件=本轮 run 结束），另有在跑子任务、或已获用户授权但被该门/终态阻塞的后续步骤

## Discriminator
deferred 回执自身已写明三要素——生效时机（run 结束 worker 自动接手）、机器可查的终态判据（status=succeeded 且 live 指纹=desired 指纹）、出口（natural/override），加上在跑子任务回执的 est 完成时间。这四项合起来已把『何时核、核什么、核完走哪支』全部定死：会话内轮询只会重复证实已声明的 waiting，而用户已授权续办意味着无需再询问——唯一剩余未知量只是唤醒定时与条件分支的编排

## Short path
- 读 deferred 回执提取三要素：生效条件（pending、条件=本 run 结束）、终态判据（assert=状态成功+live 指纹=desired 指纹）、出口（natural/override）——解决『何时能核、核什么』
- 盘点收尾时全部未终态轨（deferred 服务动作、在跑子任务、预授权后续步骤），各记判据入口与 ETA——解决『唤醒后要处理什么』
- 注册单个定时唤醒：时长对齐最长轨 ETA（可略提前），载荷逐轨写条件分支（子任务 PASS⇒执行预授权步骤 / REVISE⇒修复重审 / deferred 轨仍 waiting⇒按 exits 处置）——解决『唤醒后第一步做什么』
- 向用户报告真值：已受理未生效（旧代仍在服务）+ 续办已排定 + 不归本会话动的遗留，显式不作完成宣称——解决『用户此刻该知道什么』
- 会话结束触发 worker 接手；唤醒后逐轨按其 assert 查终态，全部闭合后才作完成报告

## Stop conditions
- 所有未终态轨均已取得权威终态并向用户报告，才允许完成宣称
- 某轨下一步需要超出已获授权的代价（如 override 立即生效会切断会话）→ 停下呈报用户裁决，不自行选择
- 唤醒后判据入口不可达或回执自相矛盾 → 按失败处置并保留待确认，不猜测终态

## Verification
- 唤醒后每轨按其回执自带判据核对：action 状态=succeeded 且 live 指纹=desired 指纹、收敛列表不再含该服务；子任务取 PASS/REVISE 终态
- 中间读数显示旧 generation 或缺新字段时判『未收敛』而非失败/未实现（回执由部署前进程生成，新字段要等新代收敛）
- 作完成报告前确认没有任何轨仍处 waiting/running；有则按其 next_check.exits 处置

## Counterexamples
- 所有轨均已终态且无 deferred 项 → 直接报告即可，注册唤醒纯属空转
- 后续关键步骤（不可逆 push/发布）未经用户授权 → 不得打包进自动唤醒执行，须先呈报差分获授权
- 没有任何 ETA 或生效时机判据可对齐 → 盲定时不如结束即查或交用户定夺
- 单一 deferred 轨且无预授权续办 → 只需向用户交出出口选项裁决，无需构造多轨条件计划
