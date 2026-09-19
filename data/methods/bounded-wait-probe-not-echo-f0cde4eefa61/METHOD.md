---
method_id: bounded-wait-probe-not-echo-f0cde4eefa61
name: bounded-wait-probe-not-echo
description: 识别'原样重复一个输出已确定为常量的动作'为无信息循环：任何等待必须要么探测所等条件、要么声明有先验上界的预算；每个重复动作的输出都应能决定继续或停止，而不是只能靠用户取消终止。
status: candidate
source_model: glm/glm-5.3
teacher_refs: method:method-self-distill-root-cause,method:method-self-distill-repo-api,method:method-self-distill-ab
source_episode_refs: session:2274a444-654d-46a3-a72b-2d83058b2289
created_at: 2026-09-10T00:20:11.593717+00:00
updated_at: 2026-09-10T00:20:11.593717+00:00
---
trigger:
  - 准备再次执行与上一次完全相同的动作（同命令同参数），且上一次输出为确定性常量（固定 echo 文本、退出码 0）
  - 等待类任务：等时间点 / 等外部条件 / 等累计轮数
discriminator:
  - 看第一次执行结果：输出是否包含任何会变化的未知量？若命令本身不探测任何状态（如 echo 常量），重复 N 次在信息上完全等价，循环没有内生退出判据
  - observable 特征：连续相同 fp_summary 且输出逐字节相同；最终以外部 kill（退出码 -9 / 用户取消）结束而非自身条件命中
short_path:
  1. 等待前先命名"在等什么"：时间点 C、外部事件 C、还是累计轮数 B
  2. 纯时间等待：声明总预算（N 次 / 总时长），可合并为更长的单次等待，并向用户汇报倒计时
  3. 事件/资源等待：把探测并入等待命令，使每次输出编码 C 的状态（查文件/进程/端口/日志），任一次结果即可决定继续或停止
  4. 每次探测对照停止条件；连续 K 次输出无变化 → 停止并上报/询问，而非继续盲等
  5. 若任务本意是周期性空转（keep-alive / 采样统计），先声明轮数预算与进度检查点，使终止可预期
stop_conditions:
  - 所等条件 C 被观测到；声明预算耗尽；连续 K 次探测无变化；到达用户可见检查点
verification:
  - 不存在超过 K 个 fp_summary 相同且输出恒定的连续调用；每次重复动作的输出都能改变继续/停止决策；重复总次数有先验上界
branch_on_evidence:
  - observation: 命令输出恒定且不含任何状态探测
    next: 改造为带探测的轮询或显式声明预算，禁止原样重复
  - observation: 输出随等待条件变化
    next: 已是有效轮询，按停止条件收敛
  - observation: 用户显式要求固定间隔重复（心跳/限速）
    next: 保留重复但声明预算与进度上报
anti_patterns:
  - 原样重复一个输出已知的确定性命令
  - 无退出谓词的静默等待循环，只能靠用户手动取消结束
counterexamples:
  - 任务显式要求固定心跳或 API 限速间隔，重复本身就是目的（仍应声明预算与进度）
  - sleep 命令内嵌状态检查且输出可变，属有效轮询，不适用本方法
  - 单次等待超过工具超时必须分段，分段合理，但仍需总预算上界
programizable:
  - 检测连续 K>=2 个 fp_summary 相同且输出逐字节相同的工具调用并告警或阻断
model_owned:
  - 判断"在等什么"、重复是否被用户显式授权、何时升级为停止上报或询问用户
why_shorter: 把无界同构循环变成有界序列，每步输出都能触发终止决策，不再依赖外部取消作为唯一退出机制。
