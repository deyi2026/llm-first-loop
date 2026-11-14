---
method_id: ast-normalized-equivalence-before-textual-diff-paging-37a0b763ca72
name: ast-normalized-equivalence-before-textual-diff-paging
description: 验证『提取helper/纯格式合并/import上提』类机械重构的语义等价时，不要分页读取数百行以代码搬运为主的文本diff（截断率高、信号低、会触发读媒介轮换：diff→/tmp暂存→read_file→sed分段）：先用任务书与diffstat给每文件定性；format-only用两版ast.dump全文件比较一次定性；extract-helper先验调用点形状（简单名按位实参、调用后显式return、无闭包/默认参/中途return），再写内联回代脚本剥docstring后ast.unparse字节比较，等价性一次机械判定；import上提单独核名字存在与反向import边——AST看不到fail-open变启动硬失败的时机语义；跑测试前先钉解释器解析路径防快照污染。读力只花在AST不可见的边上。
aliases: 大段搬代码的diff怎么审, 提取helper重构等价审查, AST内联回代证等价, 纯格式改动快速验证, 重构没改逻辑怎么确认, 几百行diff全是搬运
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b83e3a29-c697-42ad-b8b5-264143eb0bf5:0:8eeda5e84bed00c0b75e
evidence_refs: learning:learn:d76951ddd3eb
created_at: 2026-11-14T11:58:54.455507+08:00
updated_at: 2026-11-14T11:58:54.455507+08:00
---
## Trigger
审查/验证任务要求确认一次已声明形状的机械重构（提取N个helper、括号换行合并、导入并入既有顶层import）的语义等价，且最大文件diff达数百行、以整块代码搬运为主

## Discriminator
任务书已逐字给出重构形状（如『383→192 AST行，提取3 helper』『仅合并两处无意义括号换行』『导入移到已有顶层』）且首个命令的diffstat证实（436行改动242+/205-、engine仅8行、factory仅3行）——这些先验事实当时已把未知量缩成『规范化AST是否等价』，逐行文本比对是冗余媒介；首个truncated diff hunk中helper函数体与旧内联块逐字相同进一步确认这是代码搬运

## Short path
- 一条命令收齐机械事实：HEAD/tree/parent/porcelain/diffstat/name-only
- 按任务书+diffstat给每个改动文件定性：format-only / import-hoist / extract-helpers
- format-only：两版本 ast.dump 全文件比较，一次命令定性
- extract-helpers：先核对每个调用点形状（简单名按位实参、调用后显式return、helper无中途return/闭包/默认参），再写内联回代脚本，剥docstring后 ast.unparse 字节比较
- import-hoist：AST之外单独核验——目标名字在目标模块实测存在+无反向import边（grep）
- 跑测试前先清理解析污染源（如宿主PYTHONPATH指向发布快照），实测import解析到工作树源码后才采信测试结果
- 规范化AST等价成立+import边核验通过+守卫/专项全绿即停止，出裁决

## Stop conditions
- 内联回代后两侧 ast.unparse 逐字节相同，且import边/名字存在性核验通过
- 任一调用点不满足可安全内联形状（kwargs/默认参/闭包捕获/helper中途return）→ 放弃机械内联，转逐hunk文本审查
- 规范化AST不等 → 直接判非等价重构，转REVISE并定位差异，不再读搬运代码

## Verification
- 内联回代脚本只做机械替换+unparse，新旧字节比较结果可独立复算
- 测试在确认目标包解析到被审工作树源码（非快照/主仓安装）后实跑且全绿
- 每个helper调用点后的显式return与旧内联版return一一对应

## Counterexamples
- 重构夹带逻辑修改（条件重排/操作符/early-return顺序变化）：字节比较必然不等，AST等价只剩单向证据，须回文本hunk或定向测试定位
- 调用点用kwargs/默认参/闭包捕获、helper内中途return：朴素内联替换不可靠，须先验形状或放弃该法
- 无AST工具链的语言、生成/压缩文件：退规范化文本diff或行为测试
- diff仅几十行：直接读比写脚本更快
- AST等价不覆盖import时机语义（名字缺失由fail-open变启动ImportError一类边界变化，本集P2-1），必须另行核验
