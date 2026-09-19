---
method_id: alien-literal-polluter-hunt-fceef795e7c0
name: alien-literal-polluter-hunt
description: 当测试只在全量套件中失败、且断言 diff 中的 actual 是不属于本测试的外来字面量（另一测试的 fixture 标记串）时，先 grep 该字面量的生产者定位污染源，并用秒级 pair-run 确认因果；而不是为拿 traceback 重跑全量套件，或宽枚举文件做人工二分。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T20:40:13.657313+00:00
updated_at: 2026-09-09T20:40:13.657313+00:00
---
trigger:
- 某测试在全量运行中稳定失败，但任务早期的小范围组合/单文件运行未见过该失败（全量专属失败）
- 已读过被测运行时代码，可见其从进程级/上下文级 ambient state（contextvar、env、全局单例、共享 registry）解析身份或配置
- git log 显示最近提交恰好新增了同域测试
- （拿到 traceback 后）断言 actual != expected，且 actual 是一个本测试从未设置过的外来字面量
discriminator:
- 外来字面量本身即判别器：expected 是本测试显式注入的值，actual 必然由其他代码生产——把"哪个测试/顺序污染"缩成"grep 这个字面量谁写的"
- 全量专属失败 + 运行时优先读 contextvar/环境态的设计注释，两者组合即支持"跨测试状态泄漏"为首选假设
short_path:
1. 一次全量跑锁定失败 test id（已有，不再为同一目的重跑）
2. 读 victim 测试源码（秒级）：确认断言依赖哪个 ambient 值（如会话 id），以及测试只设置了显式回退值
3. 对照已读运行时代码：该值是否优先从 contextvar/env/global 读取 → 泄漏假设成立
4. 在测试目录 grep 该 ambient state 的写入点（.set( / environ 赋值 / 单例变更），检查是否缺 reset/teardown → 命中无恢复的污染测试
5. 最小 pair-run（污染文件 + victim，--tb=long）秒级复现确认因果；补 reset/fixture 后 pair-run 与单跑均绿即停
branch_on_evidence:
- observation: 单独运行 victim 也失败
  next: 是 victim/产品代码自身 bug，放弃污染假设，直接读 traceback 与产品路径
- observation: actual 是被测代码生成值（哈希/uuid/时间戳）而非 fixture 字面量
  next: literal-grep 无唯一生产者，回到读产品代码的生产路径
- observation: 顺序随机插件在场导致失败不稳定
  next: 先固定顺序（禁用随机 / --lf）再定位
stop_conditions:
- 污染者满足三证：字面量生产者 grep 命中、pair-run 复现、加恢复后 pair-run 与单跑均通过
verification:
- 最终结论必须包含最小因果实验（polluter+victim 前后对比），而非仅凭 grep 相似度断言
anti_patterns:
- 为获取已知失败测试的 traceback 而重跑整个慢套件（污染类失败只需 polluter 在场，pair-run 即可拿到 traceback）
- 枚举全部字母序前驱文件做人工二分
- 对长后台任务反复 sleep-poll，而不先跑快速判别实验
- 在泄漏假设已成立后仍继续排查无关 env/插件分支
counterexamples:
- victim 单独运行即失败 → 非污染，直接修代码/测试
- 断言 diff 无外来字面量（都是本测试可控值）→ 本方法不适用
- 纯时序/并发 flaky，与 ambient state 无关
- 泄漏源是 conftest/插件级而非具体测试文件 → grep 测试目录会漏，需扩大到 conftest/fixtures
programizable:
- 解析 assertion diff，若 actual 为字符串字面量且出现在其他测试文件中 → 输出 polluter 候选排序
- 静态扫描测试中 ambient state 写入点是否缺匹配恢复（token/reset/teardown）
- 自动生成 pair-run 命令建议（polluter+victim）
model_owned:
- 判断 actual 是否语义上属于其他 fixture 而非产品输出；判断泄漏根源是测试卫生问题还是运行时优先级设计问题；判断何时证据已足够停止
why_shorter: 把"N 个测试/顺序谁是污染者"缩成"grep 一个外来字面量的唯一生产者 + 一次秒级 pair-run"，省去第二次全量跑、多轮 sleep-poll 与宽枚举二分。
