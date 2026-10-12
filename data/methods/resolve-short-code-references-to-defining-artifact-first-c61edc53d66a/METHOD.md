---
method_id: resolve-short-code-references-to-defining-artifact-first-c61edc53d66a
name: resolve-short-code-references-to-defining-artifact-first
description: 用户用短代码(R3/F10/P4…)征询“是否需要/怎么做”时，代码含义是文档相对的，多子系统仓库常有同名编号系列(Recoverability-R系、cache-R系、service-control-R系)。先解决唯一未知量“哪个 artifact 定义了这组代码”：用用户话语中的命名空间词或按新近度(ls -t docs / git log)定位定义文档，再只在该文档内 grep 代码取定义与验收标准；不要裸代码全文搜索。拿到定义后，只为会改变取舍结论的承载性论断做代码/日志核验，未核验项显式标注。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fc0ed66c-e669-41c4-94d7-7e05031bbac6:469:bc46befa308672d971d0
evidence_refs: learning:learn:c7b8a41979d4
created_at: 2026-09-22T17:34:38.220007+00:00
updated_at: 2026-09-22T17:34:38.220007+00:00
---
## Trigger
用户引用短的不透明代码/编号(R3、F10、P4 等)并询问是否需要、优先级或怎么做；这些代码的含义依赖某份具体 spec/proposal，而工作区存在多个子系统的相似编号系列；或搜索工具对组合长查询未命中后需要选择回退策略。

## Discriminator
用户提问本身成对出现两类词：含义模糊的短代码 + 无歧义的命名空间词(如“修复包/restart”)，且“是否需要”表明这是待评审的近期提案；因此唯一首要未知量是定位那份定义文档，可用新近度通道(最新 docs 列表、git log 中的 spec 落盘提交)或命名空间词限定搜索一步命中，而裸代码搜索必然撞上其他同名编号系列。

## Short path
- 从用户措辞提取：短代码 + 命名空间词 + “是否需要”→ 判定这是对某份近期 spec/proposal 的评审请求；明确唯一未知量=哪份文档定义这些代码。
- 用新近度通道(ls -t docs/*.md、git log 找 spec 提交)或用用户的命名空间词(“修复包”/“restart fixpack”)做限定搜索，定位定义文档；不用裸代码搜全文。
- 只在该文档内 grep 各代码，抽取每项的定义、优先级、验收复选框与问题证据映射。
- 通读该文档获取 R 项与底层问题(P 项/F 项)的对应关系。
- 仅为会改变“保留/砍掉/降级”结论的承载性论断做定点核验(如具体代码路径 reaper 行为、worktree/env 残留位置)；核验不了的显式标注“未重查”。
- 逐项给出建议及实现形态修改；每个结论都有 spec 事实+已核代码/日志事实支撑即停止。

## Stop conditions
- 定义文档已定位且每个代码的含义与该文档原文核对一致(而非来自其他同名编号系列的搜索片段)。
- 每条保留/砍掉/降级建议都引用了 spec 内定义事实，并有已核验的代码/日志事实或显式的未核验标注。
- 不再对已排除命名空间的命中结果做后续搜索。

## Verification
- 对照定义文档原文行，确认最终答案中 R3-R6 的语义来自该 spec，而非其他 R 系列的搜索命中。
- 对每条“冗余/已被覆盖”的砍除建议，能指出核验过的具体代码路径或日志位置。
- 答案中明确列出本次未核验、按既有证据采信的项目。

## Counterexamples
- 代码是全局唯一标识(HTTP 404、CVE 编号)或仓库只有单一编号系列→裸代码搜索一步命中，新近度绕行只增加成本。
- 用户问的是具名函数/机制的实时运行行为(“reaper 会不会释放屏障”)→应直接读源码，文档新近度无关。
- 定义分散在多份旧文档、无近期 spec→ls -t 新近度优先会漏；应查 registry/索引文档或直接向用户索要文档标识。
