---
method_id: live-process-anchor-verify-deployment-claims-b3abbf2f86e4
name: live-process-anchor-verify-deployment-claims
description: 核实"已部署/已重启/端口可达"类声明时，先用进程表锚定已知服务的真实进程（PID、命令行、启动时间、实际监听端口），把部署 registry 状态与二手报告里的裸数字仅当作待核对声明。即时 connection-refused（HTTP 000 毫秒级）且该数字不在 LISTEN 表中，即可判定它不是端口（多半是 PID），不要随即展开全系统端口枚举；再用进程启动时间对比重启 action 终态，区分 desired 记录与 live 事实。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:518:173162f65da2c33e22fb
evidence_refs: learning:learn:01c3f6543b12
created_at: 2026-09-18T17:21:43.060621+00:00
updated_at: 2026-09-18T17:21:43.060621+00:00
---
## Trigger
需要验证某服务/部署是否真的生效，且手头证据是：control-plane 状态记录（generation/status/artifact sha）或二手报告给出的未标类型数字端点，同时本机可查进程表。

## Discriminator
一条即可缩窄空间的事实：按已知服务模块名或仓库路径 pgrep/ps 得到唯一存活进程，其 PID、cmdline、启动时间一次取得；再对该 PID 查 socket 即得真实端口。若二手数字 curl 立即返回 HTTP 000（0.0002s 级 connection refused）且不在 LISTEN 输出中，则该数字不是端口。

## Short path
- 从部署记录取服务身份/代码根；pgrep -af <服务模块名> 得 PID+cmdline+启动时间（未知量：现在真正在跑什么、何时启动）
- lsof -p <PID> -iTCP -sTCP:LISTEN 得真实端口，curl 一次确认状态与 auth 行为（未知量：可达性、验收是否被登录墙挡住）
- 若被 auth 挡住：停止绕过尝试，转 artifact 级证明——确认静态挂载是磁盘直读还是启动快照，复算 served 目录 tree sha 对比 registry sha
- 用进程启动时间对比重启 action 终态（如 waiting_for_requester_exit）与 registry generation，判定"已落地"是 desired 还是 live（未知量：记录与现实的差）
- 每条声明（合入/构建/部署/重启）标注证据类型后收尾；登录后才能完成的页面级验收明确交还用户

## Stop conditions
- 唯一存活进程的身份、启动时间、实际监听端口已确认，且与 curl 实测响应一致
- 所有部署声明已分类为 process-backed 或 record-only，差异已如实报告
- auth 挡住的验收项已明确为用户侧步骤，不再尝试绕过或继续枚举配置找口令

## Verification
- lsof -p <PID> 列出的监听端口，恰是 curl 得到 HTTP 响应的端口
- ps 启动时间、重启 action 终态、registry generation 三者对账，解释 desired 与 live 的差
- served 目录 tree sha == registry 记录 sha，且挂载语义（磁盘直读 vs 启动快照）已从源码确认

## Counterexamples
- 服务跑在远程主机/容器，本地无进程表：应以 registry 与配置端口为锚，本方法不适用
- 数字有配置出处且已验证类型为端口（如 .env 中 WEB_PORT）：直接连通性测试即可，无需进程绕行
- 用户明确要求视觉/渲染级验收：bundle sha 与挂载语义只证明"服务的是新文件"，不能替代浏览器实际渲染观察，不应据此宣称"页面已验收"
