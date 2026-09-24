---
method_id: isolation-config-visibility-seed-and-identity-gate-77b2f298c154
name: isolation-config-visibility-seed-and-identity-gate
description: 当隔离修复（per-run/per-test 独立 data 目录、沙箱、临时目录）切断了子系统原本可见的配置注册表时，配置解析链末端的『env 合成/默认值』分支会把解析失败静默化成错误 provider/默认端点继续运行，下游才报错。方法：先读解析链确认末端回落分支；枚举启动器所有设置隔离目录的位置；把无会话态纯配置（仅含密钥变量名、无原始密钥）随隔离目录播种；源缺失改 fail-fast 禁止静默回落；加硬门断言解析出的 client 身份前缀==配置的 model 前缀；负/正双向验证后才放行。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:1231:b25a45fc1f22550f2b0c
evidence_refs: learning:learn:d267a0883f26
created_at: 2026-09-22T15:56:06.463616+00:00
updated_at: 2026-09-22T15:56:06.463616+00:00
---
## Trigger
子系统被移入隔离的 data/config 目录后，出现『配置了带 provider 前缀的 model，但错误来自默认线』的故障（如网关全灭 400）；或正在做数据面隔离修复需评估副作用；或用户指令明确禁止某默认回落。

## Discriminator
首个工具结果已同时暴露两条可判别事实：(1) 配置加载优先级链末端分支『目录内注册表缺失 → 由 LLM_* 环境变量合成单 provider（默认 base_url）』；(2) 启动器源码中已可见的隔离目录赋值点（DATA_DIR=独立目录）。二者并存即可把候选空间缩成『沿链播种配置+断言解析身份』，无需考古 run 创建历史或枚举入口。

## Short path
- 从故障签名读配置解析链源码，定位各配置文件读取目录与末端静默回落分支——未知量：失败实际走了哪个分支
- 枚举启动器中所有为子进程/in-process 设置隔离目录的赋值点——未知量：共有几个隔离面需恢复配置可见性
- grep 待播种配置文件确认是无会话态纯配置（仅密钥变量名，无原始密钥）——未知量：复制进隔离目录是否安全
- 在每个隔离面播种注册表；源注册表缺失即 fail-fast，拒绝任何静默回落到 env 合成默认线
- 加回归硬门：model 带 provider 前缀时，解析出的 client 身份必须同前缀，否则门不放行
- 双向验证：负测试（空隔离目录）复现回落签名且被门击杀；正测试解析正确且首轮真实执行落盘成功，然后停止

## Stop conditions
- 解析出的 client 身份与配置的 model 前缀一致，且负测试证明回落路径已被 fail-fast/硬门拦截
- 所有隔离面已播种，首轮真实执行以预期 provider 产出结果且无数据面泄漏

## Verification
- 负测试：空 DATA_DIR 下复现默认线身份签名，门以非零退出击杀
- 正测试：资格门全绿且记录的 resolved 身份==配置前缀
- 播种文件密钥扫描：仅含 api_key_env 类变量名，无原始密钥字面量

## Counterexamples
- 部署本就设计为靠 env 合成单 provider：fail-fast 会误杀合法运行；断言应仅在 model 显式带 provider 前缀时生效
- 注册表文件含原始密钥：不得复制进 per-run 隔离目录，应改为引用密钥变量名或注入机制
- 错误为瞬时网络/认证问题且解析身份本就匹配配置：播种与门均无效；判别依据是 resolved 身份签名而非错误码本身
- 无隔离边界、原配置目录本就可见：无需播种，直接修上游配置即可
