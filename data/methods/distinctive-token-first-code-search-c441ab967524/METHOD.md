---
method_id: distinctive-token-first-code-search-c441ab967524
name: distinctive-token-first-code-search
description: 在代码库内容检索某符号的调用点/断言面时，先用当前已读定义面里最独特的裸标识符做子串检索（本集 aggregate_interject_metrics 一次命中 7 条全相关）；不用常见域词裸搜——compact 与 compaction/compact_ratio 撞车返回整页无关噪声；也不用带 '(' 的调用语法直接搜——正则引擎报 PatternError。撞词时改用转义后的精确调用式或回到已打开的定义文件/装配点内查内部调用，而不是换措辞全库重搜；PatternError 只做一次元字符转义重试。与 method-repo-api-discovery（查契约防猜签名）互补：本方法管检索键的选择与格式卫生。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1897dc0c-c278-413c-b54d-22c50b97372f:1067:d41bd49c2bcd68137bcb
evidence_refs: learning:learn:e89be58190e9
created_at: 2026-10-14T11:53:52.677765+08:00
updated_at: 2026-10-14T11:53:52.677765+08:00
---
## Trigger
需要在大型代码库中定位某函数/方法/fixture 的使用者、调用方或既有测试断言面，且手中已能从已读定义、文档或报错里看到一个具体符号名。

## Discriminator
检索发出前即可判别三件事：(1) 符号名是否含多词下划线等独特成分——独特则裸子串搜即可精准；(2) 是否为常见英文单词且与该仓库领域词汇重合（如 compact vs 上下文压缩域）——重合则裸搜必噪声；(3) 检索模式是否含 '(' 等正则元字符——含则先转义或改用裸名。本集同会话内已有实证：独特名裸搜 7/7 精准、常见词裸搜 10 条全是域噪声、两次带括号模式两次 PatternError。

## Short path
- 从已读定义/文档提取最独特的符号名，直接裸子串检索（aggregate_interject_metrics → 7 条全相关命中），按路径分组读定义面与测试面
- 符号是常见词（compact）时不在全库换词重搜：改用转义精确调用式 \\.compact\\( ，或回到已打开的定义文件与已知装配点（如 routes 的 _human_turn_queue）内部定位调用
- 收到 PatternError 时，仅做一次元字符转义修正后重试同一查询，不做语义性改写或放弃
- 命中仍为纯领域同义噪声（配置项/摘要器/别的子系统）时，放弃检索分支，直读定义文件剩余区间找内部调用点

## Stop conditions
- 已取得目标符号的定义面、足够调用点与既有测试断言面，可开始改代码
- 转义重试仍报错，或命中经路径判别全部为领域同名词噪声 → 停止检索分支，转直读文件

## Verification
- 逐条检查命中能否映射回目标符号：文件路径与模块归属无领域同名词混入
- 调用点集合与已读定义面的函数签名一致（参数/所属类匹配）
- 同一查询无重复发出；PatternError 后的重试不超过一次且模式已转义

## Counterexamples
- 目标符号本身就是领域常用词（如查 compaction 配置 compact_ratio）时，裸搜该词正是正确入口，不应回避
- 检索工具为纯字面子串匹配（非正则）时，foo( 调用语法可直接用，无需转义
- 全新探索阶段手中没有任何已知符号名/定义面时，宽泛检索仍是必要手段，本方法不适用
