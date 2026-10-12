---
method_id: match-verification-granularity-to-claim-47645b9a0a43
name: match-verification-granularity-to-claim
description: 核验第三方 review 的具体事实主张时，先把主张拆成离散断言清单，再为每条选择与其粒度一致的检查：数量/缺失类按名称级对照（可对被引用 commit 做 git show 提取同名条目 diff），'某上下文从未调用'类枚举该符号全部 call sites 后逐一定位排除，代码不变量类直接 grep 定位符号后只精读相关行段。若检查结果与主张表面矛盾（如测试文件存在但主张称'五个测试缺失'），把矛盾当作粒度信号去细化到名称级，而不是当作对主张的否证。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:622:08db114236d988a21a2e
evidence_refs: learning:learn:bc867630664b
created_at: 2026-09-18T18:50:19.481416+00:00
updated_at: 2026-09-18T18:50:19.481416+00:00
---
## Trigger
拿到一份包含具体事实主张（指名符号、数量、commit SHA、'缺失/未调用/仅 N 处'等）的 review/分析文档，需要在真实代码库逐条机械核验其事实层时

## Discriminator
主张文本自身指明的粒度：是否点名具体符号/数量/SHA。若点名，则'容器存在'（测试文件在）与'项缺失'（那五个测试名不在）不构成矛盾——本 episode 在发现测试文件存在的那一刻，已可见文档列出三项 invariant 名称、'五个 deterministic tests'与 SHA，足以把检查从文件级缩到名称级对照，避免过早下'GPT 说错了'的反向结论

## Short path
- 把 review 拆成断言清单：版本/计数、符号缺席、逐条代码不变量、'N 个测试缺失'，每条对应一个未知量
- 计数类用单条 git 命令核对；缺席类用一次 alternation 内容搜索（A|B|C）合并完成，不逐个枚举
- 不变量类在目标文件内 grep 定位符号（如 def read / lease 块 / 子进程 env 构造）后只精读相关行段，不做仅起定位作用的额外全库搜索
- '从未在上下文 C 调用'类主张：全库枚举该符号全部 call sites，逐一定位其所在上下文并排除 C（runtime 内唯一调用点是 CLI 即可定论）
- 'N 项缺失'类主张：git show <被引SHA>:<路径> 提取条目名写入临时文件（/bin/sh 下不用进程替换等 bashism），与当前树做名称级 diff，顺带可发现子集/超集关系
- 每条断言拿到 verdict 即停；汇总时注明粒度差异与任何附带发现，不继续'再确认几个'

## Stop conditions
- 清单内每条断言都有机械 verdict（成立/不成立/不可机械判定），且没有未解释的粒度矛盾残留
- 被引用 SHA 本地不可达或主张未指名可检对象时，停止细化并标注'不可机械判定'，不延长搜索补答案

## Verification
- 对每条'缺失'断言回查：检查是否发生在主张声明的粒度（测试名/函数/符号级），而非文件或目录级
- 对每条'未调用'断言回查：确认枚举了该符号全部 call sites 并逐一排除了目标上下文
- 对表面矛盾回查：最终解释必须是粒度差异，且两侧事实（文件存在 vs 具体项缺失）同时为真

## Counterexamples
- review 只给笼统主张（'X 模块未完成'）且不指名符号/数量：符号级存在搜索已是正确粒度，细化到名称级是浪费
- 被引用 commit 在本地仓库不可达：名称级 diff 不可用，应退回语义对照而非硬套本方法
- 主张是评分/预测/主观判断（如'预计可达 9.6 区间'）：不属于可机械核验断言，不应启动该流程
- review 引错了文件、容器与断言确属无关对象：此时文件级矛盾直接否证主张，无需再细化粒度
