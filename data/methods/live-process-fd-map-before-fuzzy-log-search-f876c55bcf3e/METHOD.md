---
method_id: live-process-fd-map-before-fuzzy-log-search-f876c55bcf3e
name: live-process-fd-map-before-fuzzy-log-search
description: 本地应用崩溃/静默退出取证时，若已有存活实例（ps 或 crash report 给出 PID 与可执行路径），先 lsof -p PID 枚举其打开的常规文件并按目录前缀聚类，得到权威 data/log/config 根目录；之后只在该根内定位日志与数据。避免在 ~/Library 各处按应用名模糊 grep 或 find 整个 home——那会命中系统 Console 与无关同名应用，且在 lsof 已揭示答案后仍可能重复枚举。配套判断：用『有无 .ips + 栈是否一致』区分崩溃与静默退出；用 codesign 结果判断二进制可改性。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a962d90b-199e-4a0c-af2f-3ce28b719bfb:300:59a5436e1360e46d0b80
evidence_refs: learning:learn:09d0d02d3357
created_at: 2026-09-23T07:00:36.603828+00:00
updated_at: 2026-09-23T07:00:36.603828+00:00
---
## Trigger
诊断本机安装的桌面应用/后台服务的崩溃、挂起或静默退出，且当前存在存活实例、PID 与可执行路径已知，需要定位其运行时日志/数据/配置的实际位置

## Discriminator
ps 输出已给出存活 PID（如 49786）与完整可执行路径，crash report 头已给出 procPath/bundle id——一条 lsof -p PID（过滤 REG）即可把『日志/数据/配置在哪』从全部标准目录的名称枚举缩为该进程实际打开的一棵目录树

## Short path
- 三路并行只读取证：ps 确认存活 PID 与进程名、ls 应用安装位置、ls DiagnosticReports 按 app 名过滤，先判定『昨天崩溃 vs 今天静默退出』两个未知量
- 读一份 .ips 头确认 procPath/异常类型；如用户问题涉及能否修改，则 codesign -dv 判断签名类型（adhoc→可改可重签）
- 对存活 PID 执行 lsof -p PID | grep REG，把返回路径按父目录聚类取最大公共前缀，即得 data root（取代 grep ~/Library/Logs 与 find 全 home 两轮模糊搜索）
- 仅在 data root 内 ls / find *.log，tail 主日志到事发时间窗，确认有无 panic/fatal 痕迹
- 多份 .ips 的栈逐帧对比（偏移一致→同一确定性 panic；缺失→不同根因）
- 崩溃签名、当日退出方式、可改性三类事实齐备后停止取证，直接回答用户原始问题（安装包是否必要、是否需要源码）

## Stop conditions
- lsof 已给出 data root 后，不再做任何跨目录的名称模糊搜索或全 home find
- 崩溃签名（同栈/异栈）与事发当日退出方式（有无 crash report + 日志尾部有无 fatal）均已确认
- 决定用户问题的最小事实集（应用已装于本机、签名可改性、panic 位于无符号原生二进制）已被权威证据覆盖

## Verification
- lsof 得到的路径真实存在，且 mtime 落在事发时间窗内
- 多份崩溃报告的栈帧偏移逐字节一致，才断言『同一确定性 panic』
- 事发时段无 crash report 且主日志尾部无 panic/fatal，才断言『静默退出/挂起』而非崩溃
- 最终结论直接回应用户原始问题（是否需要安装包/源码），而非只罗列取证结果

## Counterexamples
- 进程当前已死且无法立即拉起（无 live PID）→ lsof 不可用，应退回 bundle id 推断 ~/Library/Application Support/<id>、launchd plist、crash report 的 procPath 等静态线索
- 目标是进程已关闭/轮转的历史日志（不再持有 fd）→ lsof 不会列出该文件本身，只能列目录查找；但目录根仍可由其他打开文件定位
- 用户问的是安装期行为（pkg 安装脚本、安装校验逻辑）→ 安装包才是正确 artifact，运行时文件句柄无关，本方法不适用
- 系统守护进程的文件为 root 所有，lsof 需提权才能拿到完整 fd 集
