---
method_id: attribute-scan-block-to-pushed-delta-vs-scanner-fallback-087a17f015ef
name: attribute-scan-block-to-pushed-delta-vs-scanner-fallback
description: 推送闸/CI 安全扫描拦截并给出具体文件+命中模式+源提交时，先归因再动手修：①被标文件是否真在待推 base..tip 增量内；②被标源提交是否为 diff-tree 为空的 merge（扫描器全树回退→命中的是远端既有内容，非本次泄漏）；③模式是否由运行环境身份动态构造（如 CI USER=runner 撞上正文 'runner-proof' 类词）。归因结果决定修内容、修扫描器回退、改词面或登记豁免，防止把扫描器 bug 当泄漏修、或误删合法内容。
aliases: 推送被安全闸拦住先判断是不是误拦, hook拦截的文件不在待推diff里怎么排查, CI隐私扫描命中但内容远端早就有, merge提交触发全树扫描误报怎么查, 拦截回执源提交是merge说明什么, 先归因拦截再决定改内容还是改扫描器
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:3635:abc863b91928da5e4e26
evidence_refs: learning:learn:e19b856039ad
created_at: 2026-10-29T23:05:43.023142+08:00
updated_at: 2026-10-29T23:05:43.023142+08:00
---
## Trigger
pre-push hook 或 CI 隐私/安全扫描以非零退出拦截推送，回执含命中模式、被标文件与源提交 SHA；或拦截模式是随运行方身份变化的动态正则（由 USER/id -un 构造），不同环境扫描结果不同

## Discriminator
两个当时即可取得的一跳事实：被标文件是否出现在待推范围 diff 中；被标源提交是否为 diff-tree 返回 0 行的 merge 提交。任一成立即证明命中内容并非本次推送引入——是扫描器回退全树重扫已发布内容；若模式形如 <env-user>- 且正文含含该前缀的正常词汇，则为 CI 环境身份碰撞，而非真实泄漏

## Short path
- 读拦截回执，提取三要素：命中模式、被标文件、源提交 SHA
- 一跳检查A：git diff --name-only <remote-base>..<tip> 是否包含被标文件；不包含→命中非本次增量引入
- 一跳检查B：被标源提交是否为 merge 且 diff-tree 对其返回 0 行→扫描器回退全树，命中=远端既有内容，应结合该文件是否已在远端分支存在双重确认
- 一跳检查C（CI侧红）：用 CI 同名环境变量（如 USER=runner）本地复现同一扫描命令，比对退出码与命中文件，确认动态身份正则与正文正常词汇碰撞
- 按归因选修复面：内容确在增量内→脱敏重写；回退误拦→改扫描器的 merge/既有内容处理；身份碰撞→改写词面或显式豁免登记；动扫描器代码前先读其回退分支源码验证推断的因果

## Stop conditions
- 每个拦截都能唯一归因到：本次增量内容 / 扫描器回退误拦 / 环境身份碰撞 / 凭据或配置缺失，之一
- 对推断出的『回退→误拦』因果，已读扫描器源码对应分支确认，或在汇报中明确标注为未验证推断，才进入修复或上报

## Verification
- 复跑同范围扫描：归因为既有内容时，命中应与本次增量无关（改动仅涉增量文件后仍命中同一既有文件即证实）
- CI 侧等价复现：本地带 CI 环境变量跑同一命令，退出码与命中文件应与远端 CI 日志逐字一致
- 被标文件在远端分支已存在的判定用远端分支直接 grep/ls-tree 确认，而非只看本地

## Counterexamples
- 被标文件确实出现在 base..tip diff 中——真实新增泄漏，直接脱敏内容重写提交，不要动扫描器
- 命中模式是静态密钥/令牌而非动态身份构造——无论提交拓扑如何都按真实泄漏处理
- 扫描器只扫增量、源码中无全树回退分支——diff-tree 为空不构成误拦解释，需另找真实原因
- 拦截原因是凭据缺失或超时（如扫描耗时超过 dry-run 超时上限）——属于执行环境问题，归因框架不适用，应先单独定时跑扫描测耗时
