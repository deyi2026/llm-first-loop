---
method_id: edge-530-zero-traffic-resolve-hostname-tunnel-binding-via-control-plane-9296e6433628
name: edge-530-zero-traffic-resolve-hostname-tunnel-binding-via-control-plane
description: 公网域名经 Cloudflare 代理返回 530/1033、本机服务正常、且存在显示健康的 cloudflared 连接器时，不要先调试看得见的连接器：『连接健康但 total_requests=0』本身证明公网流量根本没有经过它，DNS 绑定的是另一条隧道。橙云代理会隐藏真实 CNAME，公网 DoH 查不到隧道绑定（只回代理 A 记录）；应直接从控制面权威来源（Cloudflare API 查 DNS 记录，或声明 ingress 的本地 config）解析『主机名→tunnel ID』绑定，再检查目标隧道是否有活连接器。token/named 双隧道迁移残留场景下，这能把全盘本地考古压缩成一次绑定查询。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:97877415-9ecf-4ec7-840e-a4568f1f55ed:130:b488200d02b6f24d81cf
evidence_refs: learning:learn:1e58f17170f2
created_at: 2026-10-06T21:38:39.908641+08:00
updated_at: 2026-10-06T21:38:39.908641+08:00
---
## Trigger
公网域名返回 530/1033 而本机探测正常（应用层响应），机器上运行着 cloudflared 且 metrics 显示 readyConnections>0；尤其当环境存在多套并行隧道（token/named）或近期有过隧道/launchd 重构时。

## Discriminator
连接器 readyConnections>0 但 total_requests=0：零流量证明该连接器不是公网主机名实际路由的隧道，『进程健康』≠『路由健康』；同时对该主机名的公网 DoH/CNAME 查询返回无 Answer（代理隐藏绑定）——绑定关系只能从控制面读取。

## Short path
- 对比 local 与 pub 探测，把故障层定位到 edge↔origin（隧道层），先排除本地服务问题
- 读运行中连接器 metrics：健康连接+零请求 → 假设『DNS 绑定的是另一条隧道』；当前唯一未知量=主机名↔tunnel ID 绑定
- 从控制面解析绑定：用本地服务配置中的 API token 查该主机名 DNS 记录的 cfargotunnel CNAME 目标，或读声明 ingress 的 config；不要对公网 DoH 换措辞重试（代理必然不回 CNAME）
- 检查目标隧道有无活连接器：其日志的 SIGTERM 时间点 vs 故障起始时刻，加 launchctl print 加载状态；一并验证 launchd 自愈链（plutil -lint、脚本 exec 位、服务 loaded）
- 按绑定修复正确的隧道与启动链，端到端验证 pub 从 530 变为应用层响应

## Stop conditions
- 绑定关系已由权威来源确认（API 的 CNAME 目标 tunnel ID 与本地 ingress config 声明一致）
- 目标隧道的连接器状态与日志时间线能解释 1033 的起始时刻
- 修复后 pub 端到端返回应用层响应（401 鉴权挑战也算穿透成功），total_requests 开始增长

## Verification
- API 查得的 CNAME 目标 tunnel ID 与修复后实际启动的隧道 ID 完全一致
- 修复前后对比：pub 530/1033 → 应用层响应；目标隧道 total_requests 0 → 持续增长
- launchctl print 确认相关任务处于 loaded/运行态，而非仅 plist 文件存在

## Counterexamples
- total_requests>0 且持续增长但仍 530：流量已正确路由到这条隧道，问题在 ingress/origin 侧（本地服务挂、端口错），应查该隧道的 ingress 与本地服务，不是绑定错位
- 主机名是灰云 DNS only：公网 dig 直接可见 cfargotunnel CNAME，无需控制面 API，先解析即可
- 本机 local 探测同样失败：第一未知量是本地服务本身，隧道绑定排查应后置
- 单隧道环境（无 token/named 并行）：绑定错位先验极低，优先查进程存活、协议与 edge 连接本身
