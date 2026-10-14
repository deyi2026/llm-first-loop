---
method_id: hazard-class-triage-by-declared-safety-mechanisms-a56dd5555cf5
name: hazard-class-triage-by-declared-safety-mechanisms
description: 解决并发/生命周期类结构性隐患前，先把控制面契约（工具 schema/权威文档）中显式声明的安全机制（CAS、物理阶段复核、fail-closed、自恢复）当作分诊判据：若声明已阻断『错误代部署/错误绑定』类正确性风险，剩余面就是可用性问题（屏障占用时长、恢复盲区窗口），解法应选缩短恢复窗类（reaper 扩覆盖/supersede/超时）而非加强绑定类；分诊结论必须用实体名定位实现文件做行级验证，防 schema 与代码漂移。可用性解法严禁把清除范围扩大到有物理副作用的执行态（running/verifying）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:323:55f459abd662ca5a7521
evidence_refs: learning:learn:31bc9599e29d
created_at: 2026-10-14T15:49:21.190254+08:00
updated_at: 2026-10-14T15:49:21.190254+08:00
---
## Trigger
用户要求分析并解决某机制的结构性隐患（并发/状态机/生命周期/屏障类），且该机制的契约面（工具 schema、权威文档）可读，其中显式声明了安全机制（受理 CAS、阶段复核 generation、fail-closed、终态自恢复）

## Discriminator
契约已声明的安全机制清单本身：如 schema 明写『物理重启阶段复核 generation』，则错误代部署类正确性危害已被声明阻断，隐患最坏后果被界定为可用性（占用时长/盲区窗口）而非正确性——解法类别由此可唯一确定，无需先做宽泛代码枚举或凭直觉报严重度

## Short path
- 读完整工具/服务 schema，抽取显式声明的安全机制及其覆盖范围（受理 CAS、物理阶段复核、fail-closed、自恢复）
- 用声明做分诊：正确性危害是否被阻断？被阻断→剩余面是可用性（占用时长/盲区）；未被阻断→按正确性问题处理
- 按实体名（工具/模块名）做 filename 搜索定位实现文件与配套单测，跳过 .releases 历史拷贝；不要用 barrier/generation 这类跨域撞名的普通名词做内容宽搜（本集曾命中 15 条无关 eval 指标）
- 结构 grep + 定点行读验证每条声明确实落地：受理 CAS、worker 两阶段、reaper 谓词覆盖的状态集合；reaper 调用点通常就在受理函数内，可由首个定点读直接导出
- 枚举声明未覆盖的残余窗口（reaper 谓词不含的状态、spawn 到盖章 pid 间的死亡窗口）作为修复目标
- 设计与类别匹配的解法，逐条检查写路径不变量（走标准 update 写路径挂释放钩子、读异常与缺失三态区分、supersede 后不续写）；清除类解法范围严禁扩大到有物理副作用的执行态

## Stop conditions
- 残余窗口已获行级代码证据确认，且每个候选解法通过三条检查：不破坏已声明安全机制、不扩大到副作用态、走标准写路径
- 若行级验证发现声明与实现漂移（声明的复核/谓词实际不存在或更窄），停止可用性分诊，按正确性问题重新走

## Verification
- 最终意见中每条机制事实（reaper 谓词覆盖集合、复核位置、partial 失败路径）引用具体代码行号并在成稿当轮重读核实，不转述子 Agent 或上轮报告的结论
- 对每个 adopt/reject 方案回写其违反的具体判据（如 supersede-all-nonterminal 违反副作用态边界、发布路径耦合违反单一真相源）

## Counterexamples
- 无契约面的绿地代码或无 schema 的内部模块：没有可分诊的声明，应直接枚举状态机与调用图
- 隐患本身就是被声明机制的缺陷（CAS 实现有 bug、复核被绕过）：声明无法界定后果，需根因分析/实验类方法定位
- 一次性单文件小 bug、无并发或生命周期语义：分诊开销大于收益，直接读代码修
- 契约与实现已知长期漂移且无单测锚定：不能停在 schema 声明分类，行级验证才是唯一权威，此时本方法退化为普通代码审计
