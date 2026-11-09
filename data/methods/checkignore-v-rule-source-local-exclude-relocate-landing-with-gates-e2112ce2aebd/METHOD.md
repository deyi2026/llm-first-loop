---
method_id: checkignore-v-rule-source-local-exclude-relocate-landing-with-gates-e2112ce2aebd
name: checkignore-v-rule-source-local-exclude-relocate-landing-with-gates
description: 治理产物落点（审查回执等）出现『文件在盘但从不进历史』的静默黑洞、现行补救是人工纪律（记得 git add -f）时，先用 git check-ignore -v 以一个未跟踪代表文件点名命中规则的来源：.git/info/exclude 是 per-clone 本地规则，不随仓库传播、无法用提交移除，也解释了为何黑洞只出现在本机；根治因此既不是改 ignore 也不是加纪律，而是把落点迁到不被任何规则遮蔽的新目录，并用可版本化的 fail-closed 闸（新落点被遮蔽即红的回归测试 + pre-push 拒推未跟踪落点文件/占位回执）替代纪律，同步改写引用旧落点的规则与 skill 文本，旧目录转只读归档。
aliases: 文件在盘上但git里查不到, git add 收不进回执文件, 是 gitignore 还是本地 exclude 在挡, 忘了 add -f 文件就丢了, 根治手动 add -f 的纪律, 落点目录被遮蔽换目录加闸
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:400:64a6f204cb39720985f4
evidence_refs: learning:learn:0ca3c2dadd8b
created_at: 2026-11-10T06:59:40.594663+08:00
updated_at: 2026-11-10T06:59:40.594663+08:00
---
## Trigger
仓库产物落点目录被 ignore 机制遮蔽：在盘文件数远大于 tracked 数、git status 又不显示未跟踪（静默丢失），现行流程依赖『写盘后手动 git add -f』且漏做不报错；或治理文档把遮蔽笼统归因于 .gitignore 而从未核对真正的规则来源文件。

## Discriminator
对一个未跟踪代表文件执行 git check-ignore -v：一条命令同时给出命中规则、来源文件与行号。来源是 .git/info/exclude（本地 per-clone，不随仓库传播、提交改不掉）还是版本化 .gitignore（提交可改），直接决定根治手段空间：前者只能换落点；在盘数/tracked 数之差即黑洞规模，tracked 探针不构成黑洞证据。

## Short path
- 未知量=黑洞的规则来源与作用域：取未跟踪代表文件跑 git check-ignore -v，点名来源文件/行号，区分 per-clone exclude 与版本化 gitignore，不要扫 .gitignore 各行或拿 tracked 文件当探针
- 未知量=规模与历史依赖：一次只读 census（在盘数/tracked 数/tracked 引用方分布），确认历史回执与规则/skill 文本引用需保留
- 若来源是 per-clone exclude：选定新落点并用 git check-ignore --no-index 验证 exit 1（不被任何规则遮蔽）
- 用机械闸替代纪律：新增回归测试（新落点被 ignore 即失败）+ pre-push 拒推未跟踪落点文件与未回填占位回执，逐闸用探针实测 rc
- 改写引用旧落点的规则/skill/README，旧目录声明只读归档；推送后 ls-tree 远端核实

## Stop conditions
- check-ignore -v 已点名唯一来源；新落点验证不被任何 ignore 规则遮蔽
- 回归测试与 push 闸均以探针实测 fail-closed（rc=1 且给出修复提示）
- 所有引用旧落点的活文档已改写并在远端树可见

## Verification
- 在新落点放置探针文件并尝试 push：应拒推（rc=1）并打印 git add 修复命令
- 临时提交含占位回执的文件：闸应拦截并指出具体文件与命中行
- git check-ignore --no-index <新落点样本> exit 1；推送后远端 ls-tree 确认在库

## Counterexamples
- 遮蔽来自版本化 .gitignore 且团队共识是该目录应入库：直接删规则或加否定例外即可，不必搬迁落点
- 目录设计上就该本机不入库（如本地实验产物，结论以 docs/ 为准）：遮蔽是设计而非缺陷，不应『根治』
- 文件已被跟踪：ignore 规则对它无实际效力，check-ignore 命中只说明模式匹配，不构成黑洞证据——这正是探针必须选未跟踪样本的原因
- 产物从不 push：pre-push 闸在其交付路径上永不触发，需换交付时点的闸或明示接受边界
