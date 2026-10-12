---
method_id: verbatim-quote-provenance-first-for-wrong-system-suspicion-e503040634b6
name: verbatim-quote-provenance-first-for-wrong-system-suspicion
description: 用户因某句原话怀疑"接错了系统/配置被互相覆盖"时，把引用原文当作 provenance 锚点：先在本地仓库(含 src 与构建产物)精确 grep 该字符串，命中即证明消息生产者是本系统，身份问题一跳收敛，不去枚举外部端点/进程/日志。再用文件 mtime 排定竞争写入者(面板保存 vs 自己的编辑)的先后与作用域；仅当发现真实残留错配(如带 provider 前缀的模型配了过期 env base_url)时，才定位唯一的参数胜出点并只读该段代码。命令方言沿用本会话已被成功回执证实的平台。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cba0dcfa-4656-4850-921d-1fad481ce73d:862:c6c643903ab999826ccd
evidence_refs: learning:learn:45d91436a6a7
created_at: 2026-09-20T17:32:21.158159+00:00
updated_at: 2026-09-20T17:32:21.158159+00:00
---
## Trigger
用户引用一段具体的系统/UI 消息原文，怀疑连到了错误的目标系统；或怀疑两个近期写入者(如用户在面板保存与助手改配置)互相覆盖了对方

## Discriminator
被引用消息是逐字字面量：grep -rn 精确串命中本地仓库源码或 dist bundle ⇒ 消息生产者即本系统，"接错"假设当场坍缩为单一结论；配合 stat 的文件 mtime 可进一步排定写入者先后，无需重新推导内容

## Short path
- 对用户引用的原文做全仓精确 grep(含构建产物)；未知量：这条消息由谁产生？
- 命中自身 src/bundle ⇒ 身份问题关闭；若只命中 minified bundle，回溯到对应 src 文件作为可引用出处
- 对涉及的写入目标文件(env/settings vs registry json)做 stat 比 mtime，一次调用排定'用户保存'与'我的编辑'的先后及各自作用域；未知量：是否互相覆盖？
- 仅当存在真实残留错配(如 prefixed model 配过期 env base_url)时，grep 定位默认 client 的参数选择/构造点并只读该段；未知量：运行时哪个值胜出？
- 命令方言跟随本会话已成功的平台回执(如 BSD stat -f 已成功，则 sed 用显式行号范围而非 GNU 扩展)，避免失败-重试损耗

## Stop conditions
- 原文在自有仓库命中且写入者顺序已由 mtime+内容证实 ⇒ 直接给结论，不再探索外部系统
- 参数胜出规则已在构造点代码段读到 ⇒ 端点/取值问题关闭，停止继续沿依赖链逐文件爬取

## Verification
- 最终结论引用 src 源码位置(而非仅 minified bundle)作为消息出处
- mtime 与声称的写入者及时间线一致；构造点代码行明确显示覆盖/优先规则(如 '/' 前缀强制走 registry 参数而非 env 三件套)

## Counterexamples
- 消息为动态拼接/插值字符串，精确 grep 不命中 ⇒ 应改 grep 稳定片段或产消息的函数名，而非坚持原串
- 原串在自有仓库确无命中 ⇒ 锚点失效，此时才扩大到外部日志/端点枚举
- 多个写入者修改同一文件而非各自不同文件 ⇒ 仅靠 mtime 无法排除覆盖，需内容 diff
- 目标执行环境与本地路径所示平台不一致(如 ssh 到 Linux 容器) ⇒ 不能沿用本地平台的命令方言
