---
method_id: retest-predicate-artifact-hash-not-exit-code-1deffd192b3c
name: retest-predicate-artifact-hash-not-exit-code
description: 当任务交付物是『某工件文件被真实重写/再生成』（重测快照、报告、lockfile）时，进程退出码不是成功谓词：写入路径常带条件门（环境变量/仅当文件不存在），`cmd | tail` 在无 pipefail 时会用 tail 的 0 掩盖真实失败，系统默认解释器也可能不是项目 venv。改为：运行前对工件取 sha256 快照，显式用项目解释器 + pipefail 运行，终态后第一步复算 hash——exit 0 但 hash 不变（尤其耗时近零）即判 silent no-op，换正确调用方式重跑而非枚举其他归因。本集首次重测正是 python3+tail 回执 exit 0、文件原封不动，二次 .venv/bin/python 才产出真实 diff（llm_stream p50 1240→22.7ms）。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7c026852-7867-4a41-9ab0-1340271874dc:528:0e23310e303eec0ba457
evidence_refs: learning:learn:172eba578d6a
created_at: 2026-10-22T13:07:43.859403+08:00
updated_at: 2026-10-22T13:07:43.859403+08:00
---
## Trigger
一次命令/测试运行的完成判据是特定工件文件被重写或再生成（重测快照、验收报告、lockfile 等），且满足任一：生成器写入路径带条件门（环境变量、仅当文件不存在）；命令被管道（如 | tail）包裹且 shell 无 pipefail；仓库存在项目级 venv/工具链而调用用的是系统默认解释器。

## Discriminator
启动前后已在手的事实即可收窄：① 生成器源码明确显示写入是条件式（测试通过 ≠ 文件已再生）；② 自己的环境检查已列出 .venv 存在且系统默认解释器版本与之不同；③ 终态回执的耗时与该套件真实量级明显不符（时序测试 0.0s 返回 vs 实测需 23s）。任一事实出现，即应把成功谓词从『退出码』降级替换为『工件身份（sha256/diff/mtime）』。

## Short path
- 从生成器源码确认写入条件门（如 PHASE4_OVERWRITE_REPORTS）→ 启动前对目标工件取 sha256 快照并保存副本到 /tmp
- 显式调用项目解释器（.venv/bin/python 等），shell 用 bash -e -o pipefail 或回显 PIPESTATUS[0]，不让 | tail 冒充测试退出码
- 终态后第一步复算工件 sha256：变更 → 进入 diff；exit 0 但 hash 不变且耗时近零 → 判定 silent no-op，仅按『解释器/shell/门未设』三个已知根因换正确调用重跑，不做其他归因枚举
- diff 旧快照 → 新工件，把关键新旧数值写进提交说明；hash 与 diff 均已核实即停止，不再补跑确认

## Stop conditions
- 工件 sha256 已变化，且 diff 内容符合预期 schema/契约，新旧关键数值已记录进提交说明
- silent no-op 根因（解释器/管道/条件门）已确认并已用正确调用方式重跑成功拿到变更工件

## Verification
- 运行前后 sha256 比对：after ≠ before，且 before 与预存副本一致，排除『根本没读到原文件』
- 确认 pytest 摘要行显示目标用例实际执行（N passed），排除 collection error / 0 collected 被管道截断
- diff 中仅预期字段变化；最终提交回执包含新旧数值与重测声明

## Counterexamples
- 确定性生成器合法产出逐字节相同内容：hash 不变 ≠ no-op，需以 mtime 或运行摘要行（N passed）区分，不得盲目反复重跑
- 交付物是 pass/fail 判定本身、无任何文件突变：退出码与断言输出即谓词，hash 检查是噪声
- 一次性命令、stdout 即全部交付物：无工件身份可核，不适用本方法
