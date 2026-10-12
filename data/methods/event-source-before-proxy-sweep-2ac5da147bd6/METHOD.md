---
method_id: event-source-before-proxy-sweep-2ac5da147bd6
name: event-source-before-proxy-sweep
description: 当症状以聚合计数形式已知（如 N 次 requeue/失败/重试）时，该计数必有逐事件记录面。应先定位并聚合该记录面的 reason/时间戳/job 字段：一次读取即可把多个候选假设收窄到唯一存活假设，再沿它读代码 emit 点。不要先对代理信号做宽枚举（全量锁持有者、全目录扫描）——代理探测一次只检验一个假设且证据更弱。本例一次 journal 分组即同时证伪'前台忙/锁'与'静默期漂移'两个假设，而实际先做的 436 行 run.lock 全量枚举只换来'全部无'。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:455:67dcbdba59a239daea71
evidence_refs: learning:learn:2258b6519a77
created_at: 2026-09-17T15:20:35.853303+00:00
updated_at: 2026-09-17T15:20:35.853303+00:00
---
## Trigger
任务起点已存在聚合型症状计数（如'592 次 requeue、零消费'），且该计数精度暗示存在可定位的事件记录面（journal/ledger/事件日志）

## Discriminator
计数精度本身即判别事实：能数到'592 次 requeue'就必然存在逐事件记录，且事件行携带 reason 字段——这是当时已知、比任何代理状态（锁持有者、目录、进程表）更强的证据源。分组后 reason 全为 resource_authority_changed 而非 foreground_arrived，锁假设无需枚举即被证伪。此判别不依赖后来才读到的具体 reason 值，只依赖'计数存在⇒记录面存在'这一当时可知关系。

## Short path
- 从已知计数出发，定位产出该计数的事件记录面（find/grep journal/ledger 文件），按 event+reason+job_id 聚合并计算 admit→requeue 间隔——一次解决'哪些假设存活'（排除前台忙、排除瞬态争用、识别热自旋 job 集合）
- 用唯一存活假设对应的 reason 字符串 grep 代码 emit 点，沿调用链追到抛错判定函数——解决'哪个判定条件触发'
- 读该判定的全部 fact_conflict 条件与 admit 侧装配事实（authority 配置、fallback 是否携带 generation）——解决'根因'
- 回读事件面验证伴生症状（新 job 是否从未被 admit、计数是否跨重启/跨部署代延续）确认下游机制（无终态循环、FIFO 饥饿）——解决'机制完整性'
- 缺陷链每层均有代码行级或事件行级证据即停止探测，输出结论

## Stop conditions
- 唯一根因能同时解释计数持续增长、伴生症状（如新 job 静默）与跨重启/跨代延续，且每层有行级证据支撑
- 事件面 reason 分布已证伪全部竞争假设且无未解释的事件残留

## Verification
- 用事件面证据回验每个被排除假设确实零事件支撑（如全文无 foreground_arrived 记录）
- 以根因重新预测事件面未来行为（如每 30-40ms 一轮 admit→requeue、新 job 永不 admitted），与观测时间线一致
- 确认代码 emit 点的 reason 字符串与事件面 reason 逐一对应，无未被代码解释的事件类

## Counterexamples
- 计数来自无事件日志的裸指标计数器（如 Prometheus counter）——不存在可读记录面，代理探测或代码阅读是唯一途径
- 事件行 reason 全为无信息泛化值（如统一 'error'）——分布不判别，应直接转入代码路径分析
- 调查对象是瞬态并发竞态——append-only 日志有滞后，活体状态快照（锁/进程表）才是瞬时真值，宽枚举反而正确
- 记录面已轮转截断、历史事件缺失——聚合不可靠，需结合现时探测交叉验证
