---
method_id: rederive-quoted-read-anchors-before-spawning-bounded-readonly-child-84e985030cdd
name: rederive-quoted-read-anchors-before-spawning-bounded-readonly-child
description: 派生有界轮次只读 Reviewer child 前，不得把上游 brief 转引的『短文件名＋行号区间』阅读清单原样下发。冻结态核验阶段的目录探查已可能暴露引用名在源码树无字面命中（只剩 .venv/build 的 vendored 副本或测试文件命中），或 wc 总行数装不下所引区间——这些事实在 spawn 前就已存在，二手坐标只是假设。应在派生前用一批 scoped 探查（排除 .venv/build 的词干 find＋目标符号 grep＋wc -l）重推导坐标真值：实际路径、def/调用锚点、总行数；不匹配即改写为修正坐标图写进 spawn 任务书，让 child 第 1 轮读取直接命中、零定位消耗。本集收益：child 2 轮 4 次 read_file 完成全部清单且覆盖必读区间，行号漂移由父侧注记而非 child 自行试错。
aliases: 子代理阅读清单引用的文件名不存在, 派生reviewer前先核对路径行号, spawn任务书里的行号漂移, 交给child的阅读坐标先实测定位, 只读复审清单坐标对不上冻结树
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b8874c86-eea5-40c2-8a96-5f32587b6f1e:0:95c9b3bb7b96edee1fbf
evidence_refs: learning:learn:34ba3461d749
created_at: 2026-11-13T18:54:11.456288+08:00
updated_at: 2026-11-13T18:54:11.456288+08:00
---
## Trigger
上游交接/协调 brief 要求派生短寿命只读复审 child，brief 以『短文件名＋行号区间』形式引用阅读清单，child 轮次预算紧凑且有工具白名单，父侧按合同又必须在 spawn 前先 fail-closed 核验 commit 冻结态

## Discriminator
冻结态核验的目录探查输出是否已暴露错配：所引名称在 src 树无字面命中（命中仅为 vendored 依赖副本/测试文件），或探测到的总行数无法包含所引行区间；该事实先于 spawn 存在，足以把二手文件名与行号降级为待重推导的假设，而不是可直传的路径事实

## Short path
- fail-closed 核验冻结态：rev-parse HEAD/tree/parent 三元一致＋status clean，不匹配即终止不派生
- 同批执行坐标重推导：排除 .venv/build 的文件名词干 find＋目标符号 grep（取 def 与全部调用点行号）＋wc -l，得到每份文件的实际路径、锚点与总行数
- 出现任一错配（短名无字面命中／区间漂移或超总行数）即把阅读清单改写为修正坐标图（实际路径＋原区间＋漂移注记）写入 spawn 任务书；无法定案则按任务规则 fail-closed 终止，不把歧义交给 child
- spawn 只读 child，有界阻塞轮询到 terminal；截断回执经 evidence_ref 恢复全文；模型归属直接用 spawn 回执中已有的 model 字段＋fallback 观测闭合，不再去 event_stream 换词检索

## Stop conditions
- 全部所引名称在源码树唯一字面命中且行区间被总行数包含：直接透传清单，跳过改写步骤
- 修正坐标图已写入 spawn 任务书且 child 第 1 轮读取调用全部直接命中实际路径：本方法职责完成
- 目标文件不在本 worktree（另一主机/另一仓库/打包产物）：停止本地反复探查，回到上游来源定案

## Verification
- child 工具轨迹中零文件定位类 search 调用，全部读取直接命中修正后路径
- child 报告的实际读取区间覆盖全部语义必读区间，行号漂移以注记披露而非触发重读或误判漏读
- grep 得到的 def/调用点行号与 brief 所引锚点可交叉核对，不一致处已体现在修正坐标图

## Counterexamples
- brief 已给出唯一精确绝对路径且行号经同一 commit 校验，或 child 轮次宽裕并配 search 工具可自行校准：预推导是纯开销，应直接透传
- 行号被明确声明『仅供参考』、brief 以符号名/函数名为锚：只 grep 符号锚点即可，无需行号级核验
- 目标文件不在当前 worktree：本地换不同 find 模式反复试探只会命中 vendored 副本噪音，不能定案
