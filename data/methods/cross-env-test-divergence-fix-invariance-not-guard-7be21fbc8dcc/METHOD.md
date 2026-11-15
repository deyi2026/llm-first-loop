---
method_id: cross-env-test-divergence-fix-invariance-not-guard-7be21fbc8dcc
name: cross-env-test-divergence-fix-invariance-not-guard
description: 同一冻结 SHA 的测试在外部独立环境（不同 TMPDIR/HOME/basetemp）按原命令 exit1，而本地重跑全绿时，分歧本身就是诊断：测试内嵌了环境位置假设，不是产品缺陷也不是验收误报。先读失败断言找出隐含假设（未设某个 env 时依赖 tmp 恰落默认拒绝根；fixture 目录嵌套使账本落在 workdir 内），只做测试侧最小修复使其表达环境不变式：显式 setenv 构造前提并在结束后还原、用目录兄弟关系替代绝对位置依赖、新增明确负例守住守卫语义，绝不放松生产守卫。本地无法物理复现对方 basetemp（写权限受限）时，对纯路径判定分支用只读探针喂入假想的对方路径逐分支验证（含『未设时不拒』的实证），如实披露未复现部分并声明外部复跑为最终裁决。
aliases: 本地全绿外部红的测试怎么修, 测试换个环境就挂, basetemp 位置不同导致验收失败, 测试靠临时目录位置侥幸通过, 复现不了对方环境的失败怎么验证, 测试不要赌运行环境路径
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b48361e3-45f8-43a3-95da-d91f74df19fe:386:2709d064b0e2c4eea127
evidence_refs: learning:learn:5364a5bef288
created_at: 2026-11-14T18:23:32.902616+08:00
updated_at: 2026-11-14T18:23:32.902616+08:00
---
## Trigger
外部验收方在独立沙盒环境按原命令复跑冻结提交的测试失败（给出真实 exit 码与具体失败用例名），而自己在本地同命令重跑全绿；或验收报告已明确声明双方 HOME/TMPDIR/basetemp 属不同临时目录区、要求测试环境不变式而非侥幸通过。

## Discriminator
两份回执的可对照差：双方通过/skip 计数不一致，叠加报告已写明的环境事实差（对方 basetemp 落在默认拒绝根之外、本地恰好落在内）——这表明失败断言依赖环境位置巧合而非产品缺陷；验收报告里逐用例的根因假设（哪个 env 未设、哪个 fixture 嵌套）可直接当作待验证假设集，逐条读源码核对即可收敛。

## Short path
- 定位冻结 SHA 挂在哪个 ref/worktree（branch --contains + worktree list 精确匹配），核验该树干净状态，避免在错误树上操作
- 原样重跑同一命令一次：本地绿 vs 外部红 → 判定环境依赖成立，不再反复重跑、不怀疑对方误报
- 直读失败断言源码 + 相关 fixture + 守卫判定实现，逐条找出隐含环境假设：哪个 case 未显式设 env、哪个目录关系依赖 basetemp 具体位置
- 测试侧最小修复：显式 setenv 构造前提并在循环结束还原；fixture 改为兄弟目录关系（mkdir 子目录使账本与 workdir 平级）；新增明确负例验证守卫仍拒绝重叠，生产守卫零改动
- 无法移动本地 basetemp 时，写一次性只读探针把假想的对方路径喂给守卫的纯路径判定分支，逐分支验证（显式 env 后必拒、兄弟放行、账本祖先必拒、未设时不拒=原断言环境巧合的实证）
- 跑全套门禁（同套件真实 exit0、lint、类型、安全扫描、diff --check）→ 冻结新本地 SHA → 报告如实披露未物理复现项，声明外部按原命令复跑是最终裁决

## Stop conditions
- 每个失败用例的前提都由测试自身显式构造（env、目录关系），不再依赖 basetemp/HOME/TMPDIR 的具体位置
- 守卫语义未被放松：重叠/越界的明确负例仍真实触发 fail-closed 拒绝
- 新 SHA 本地全套门禁 exit0，且只读探针结果与外部报告的每条根因一一对应

## Verification
- 同命令重跑真实 exit 0，对照外部报告逐用例确认修复点与报告根因一一对应、无把失败包装成全绿
- 只读探针覆盖守卫判定全部分支：显式 env 后追加根/子路径必拒、兄弟 workdir 放行、账本祖先必拒、未设 env 时不拒（证明原断言靠环境侥幸）
- diff 确认生产代码零改动，仅测试/fixture/manifest 变更

## Counterexamples
- 外部失败在本地同样复现 → 是真实产品缺陷，应走代码修复，环境不变式框架会误导方向
- 用例语义就是测默认拒绝根本身（必须依赖字面 /tmp 或默认路径）：不能一律 setenv 改造，环境差异须用 skip/显式钉根处理，否则会把默认路径行为测丢
- 守卫分支依赖真实文件系统状态（权限、运行时创建的 symlink/mount），纯路径只读探针不可替代真实复现，须寻找可写的等价环境
- 双方环境实为同类（TMPDIR 同区）而结果仍分歧 → 指向 flaky 或测试间顺序依赖，应查隔离问题而非环境不变式
