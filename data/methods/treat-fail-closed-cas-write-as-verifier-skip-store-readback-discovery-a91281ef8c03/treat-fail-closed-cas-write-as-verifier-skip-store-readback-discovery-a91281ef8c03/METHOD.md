---
method_id: treat-fail-closed-cas-write-as-verifier-skip-store-readback-discovery-a91281ef8c03
name: treat-fail-closed-cas-write-as-verifier-skip-store-readback-discovery
description: 条件写入调用自带期望状态参数（expected_version 类 CAS 语义）时，这次调用本身就是 fail-closed 核验器：成功⇔当前状态确为期望值，确定性版本拒绝⇔状态已漂移。因此若其余前提已直验一致、唯一未核维度恰好是该参数保护的状态，而记录读取路径超时/未定位，就不要为读它去搜索文件、枚举 state 目录或换命令重试——直接发出带期望值的写入，把回执当核验结果：成功即交付，自描述版本冲突即转入停止分支不重试。CAS 只覆盖版本维度，其余前提必须先行直验；拒绝原因必须自描述才可判定。
aliases: CAS提交当核验, expected_version当预检闸, lane状态读不到直接提交试试, 写入即核验免读回, 别为核版本枚举state目录, fail-closed调用兼核对
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:896a6dce-fd3a-4d45-94ed-29019d767556:6:f377ede64e3be3eb1b4c
evidence_refs: learning:learn:96b5aeb367cd
created_at: 2026-11-17T17:49:13.524922+08:00
updated_at: 2026-11-17T17:49:13.524922+08:00
---
## Trigger
受管条件写入（lane/队列/注册表更新类）的调用合同自带期望状态参数（如 expected_version），此前提的专用读取路径超时、失败或记录文件未定位，而其余前提已用只读探针直验一致。

## Discriminator
任务指定的调用签名本身含期望状态参数（expected_version），且伴随『不一致则停止、不重试』合同：该参数使写入具备确定性拒绝语义，写入成功与状态核验是同一原子事件，store 直读并非核验该值的唯一途径——当时即可据此跳过读取发现阶段。

## Short path
- 先用一次复合只读探针核验 guard 不覆盖的前提（HEAD/清洁状态/base 等），全部一致才继续；任一不符即停
- 剩余未知量=受管记录的当前版本；此时不再为读它而搜索文件、ls 候选目录或等待超时命令
- 直接发出带期望值的条件写入——它同时完成核验与动作
- 成功：从回执读新 version/status/head 并回报，停止
- 被自描述的版本冲突确定性拒绝：按合同转入停止分支上报，不重试、不改参数

## Stop conditions
- 条件写入成功且回执给出新 version/status/head
- 写入被确定性版本冲突拒绝——这是核验判定为『状态不一致』，立即转入停止分支

## Verification
- 成功回执的 version 应恰好等于期望值+1（如 1→2），证明期望状态在原子提交时成立
- 拒绝回执必须自描述地点名 expected/current 值，才能判定为核验失败而非瞬时故障

## Counterexamples
- guard 只覆盖版本，而任务还要求核验 owner/branch 等其他维度、且 API 不强制校验归属时，CAS 成功不等于全部前提成立，其余维度仍须直验
- 调用失败原因不自描述（超时/网络/未知错误码）时，不能把失败推断为『状态不一致』，此时读取路径是必要的
- 写入调用带额外副作用（同一调用还会改 status 或重置其他字段），使『核验性尝试』可能产生非目标变更时，应先读后写
- 任务明确要求在决策前汇报记录当前内容或指出具体分歧项时，读取本身是交付物，不能省略
- 期望状态参数缺失、调用是无条件普通写入（无 fail-closed 语义）时，直接写入既不核验也不安全
