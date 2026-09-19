---
method_id: timing-complaint-decompose-from-event-log-505c689159a2
name: timing-complaint-decompose-from-event-log
description: 当用户抱怨'两个可观察事件之间卡很久/终止信号迟迟不来'并怀疑近期改动时，先用带时间戳的逐事件运行日志对被抱怨会话做时间差分解，让代码阅读与 git 排查只跟随测量所指；而不是先按想象机制做关键词 grep 或全库枚举找代码。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:2274a444-654d-46a3-a72b-2d83058b2289
created_at: 2026-09-09T18:03:08.398324+00:00
updated_at: 2026-09-09T18:03:08.398324+00:00
---
trigger:
  - 用户抱怨的是时序体感（如：输出流停了但 done/完成态很久才到、按钮迟迟不恢复），并怀疑最近改动导致
  - 系统存在记录相关事件、带时间戳的运行时日志（event log / telemetry）
discriminator:
  - 抱怨本质是两个事件锚点之间的 elapsed-time 分解问题，而非内容正确性问题
  - 逐事件日志可直接测出 gap 内的事件构成与时长分布（请求/检查点/工具起止/终止事件）
short_path:
  1. 按修改时间或时间窗定位被抱怨会话的事件日志（一次目录扫描即可），先不读业务代码
  2. 计算'最后可见输出 → 终止事件'的 gap，统计 gap 内事件类型与时长，找出时间主项
  3. 取一个体感正常的对照会话复算同一指标，确认差异归因（如轮次/任务构成的数量级差异）
  4. 只对测量所指路径与时间窗做 git 排查：近期提交是否触碰该路径
  5. 主项已解释、改动假设已排除即停，输出结论
branch_on_evidence:
  - observation: gap 主项是某类不可见事件（如纯工具调用轮长尾、慢工具间隙）
    next: 归因于行为/任务构成；顺带提出可见性改进建议，不继续枚举流式代码
  - observation: 后端 gap 很小但用户仍感知延迟
    next: 把测量移到客户端/传输侧（渲染、断连、缓冲重放），停止后端代码枚举
  - observation: 近期提交确实触碰测量所指路径
    next: 才进入对该提交的 diff 级审查
stop_conditions:
  - 时间主项已定位且有可命名原因
  - '改动导致'假设已被限定范围的 git 历史排除
verification:
  - 对照会话用同一指标复算，归因方向一致
  - 终止事件与最后输出的引擎侧间隔实测足够小，排除投递层拖延
anti_patterns:
  - 先按想象机制做关键词 grep（bounded/deque/queue 之类）再全库枚举找代码
  - 未做时间分解前逐个读大文件、逐个 commit show
  - 对同一日志反复换窗口重算同一统计；git 查询用错路径或错年份时间窗
counterexamples:
  - 没有逐事件时间戳遥测（只有粗粒度 access log）→ 本法不适用，退回静态代码+复现/bisect
  - 抱怨是内容错误（丢字/乱序/渲染错）而非时序 → 应比对 payload，时长分解不具决定性
  - 日志缺失用户所指事件或时钟偏移 → 测量不可信，先补观测或复现
programizable:
  - 给定两个事件锚点，自动输出 gap 内 per-type 时长 top-N，并与对照会话同指标对比
model_owned:
  - 选哪两个锚点对应用户体感、对照会话是否可比、何时需要单独排查改动假设
why_shorter: 一次时间分解就把假设空间从'整个流式栈+全部近期提交'缩到'gap 内占比最大的事件类别'，后续每个动作都被测量指名。
