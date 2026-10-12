---
title: macOS 排查端口占用：lsof 查询建议加 -nP（跳过 DNS 反解析与端口名转换，显著加快输出）
scenario: "在 macOS（同样适用于其他 Unix 的 lsof）上排查端口占用/进程网络连接，运行 lsof -i :PORT 或 lsof -iTCP -sTCP:LISTEN 时，若 DNS 慢或不可达，默认输出会长时间卡顿才逐行吐出。"
root_cause: lsof 默认对每个地址做反向 DNS 解析、对端口做服务名转换；当 DNS 慢或不可达时，这些逐条解析等待主导了输出延迟，与 lsof 本身开销无关。
solution: "给 lsof 查询加 -nP：-n 跳过反向 DNS 解析，-P 跳过端口名转换，例如 lsof -nP -i :8903。省去逐条网络解析等待，输出显著加快。"
evidence: "来源为上一会话 handoff 转述，写入当回合未亲自复跑：execute_command 计时复测尝试被运行时拒绝（[状态: unauthorized] run lease fenced，effect authority 丢失）。旁证（记录库内既有事实）：2026-09-10 memory 记载本镜像环境\"监听端口用 lsof -nP -i :8903\"，既有实践与该结论一致，但该 memory 未记录性能机理，故不足以替代亲自验证。"
tags: [lsof, macOS, 端口占用, 网络排查, 性能, DNS, handoff-relay]
source:
  attempt_note: 首次提交 record_kind=experience+unverified 被拒：『experience 只用于已有证据证明生效的正向经验；未验证/已证伪内容请保存为 lesson』，本次为按回执修正后的重试
  channel: 父代理委派任务（非真人新授权）
  original_context: 上一会话 macOS 端口占用排查后的交接转述
  type: handoff_relay
status: archived
record_kind: lesson
verification_state: unverified
created_at: "2026-10-10T00:35:48.955982+08:00"
updated_at: "2026-10-10T01:01:29.691089+08:00"
---

教训/实践守则（交接转述，未亲测）：在 macOS 上排查端口占用时，lsof 查询建议加 -nP 参数；-n 跳过 IP→主机名的 DNS 反解析、-P 跳过 端口号→服务名（/etc/services）转换，可显著加快输出。示例：lsof -nP -i :8903 或 lsof -nP -iTCP -sTCP:LISTEN。

诚实性声明：本记录由父代理委派任务转入，内容为上一会话 handoff 转述；写入当回合 execute_command 因 run lease fenced（effect authority 丢失）被拒，未能在本地计时复测"显著加快"的量化程度。该结论在 DNS 慢/不可达环境下收益最大；DNS 解析快的环境差异可能不明显，使用时可自行 time 对比。首次以 record_kind=experience+unverified 写入被记录库契约拒绝（experience 仅限已验证正向经验），按回执修正为 lesson+unverified。