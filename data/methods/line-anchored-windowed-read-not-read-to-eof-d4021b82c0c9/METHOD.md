---
method_id: line-anchored-windowed-read-not-read-to-eof-d4021b82c0c9
name: line-anchored-windowed-read-not-read-to-eof
description: 当早前的 grep/search 回执已给出目标符号的精确行号时，用窄窗口读取该定义（行号前后约 15~30 行，覆盖函数体即可），而不是从该偏移一路读到文件末尾；窗口不足时只扩窗一次。把读取范围由“整文件剩余部分”压缩为“已定位符号的一个闭包”。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:641:016b7b690f0f17bc550f
evidence_refs: learning:learn:182152c5f90c
created_at: 2026-10-02T02:51:54.228317+08:00
updated_at: 2026-10-02T02:51:54.228317+08:00
---
## Trigger
读取目标是一个已定位符号（函数体/编码约定/常量定义），且之前某条工具回执中已出现“行号: def <符号>”形式的精确定位；读取工具带 offset 时默认会读到文件末尾。

## Discriminator
发出读取之前，会话中已存在 grep 输出的精确行号定位，且所需事实（函数体、canonicalization 约定等）按结构必然位于该行号后 10~30 行内——此时未知量只剩“这几行的内容”，不存在需要枚举整份文件的理由。

## Short path
- 从既有 grep/search 回执中取目标符号的行号 N（本步零新调用）
- 用窄窗口读取：sed -n 'N-k,N+k p' 或 read(offset=N-k, limit≈2k)，k≈15~30
- 检查窗口内函数是否闭合、所需约定是否完整可见；不足则扩窗一次
- 带该事实直接进入下一步设计/实现，不再触碰该文件的其他区段

## Stop conditions
- 目标符号的定义体已完整出现在窗口内（可见 def 起点与函数体结束/下一个顶层 def）
- 所需语义约定已能被复述并写进当前设计决策

## Verification
- 同一事实不需要第二次更大范围的读取即可确认
- 窗口内包含完整函数体而非被截断的半段（有闭合括号或下一顶层定义作边界）

## Counterexamples
- 首次通读一个将要修改的小模块（几百行内）以掌握整体结构——全量读是正确做法，不要套用窄窗
- grep 未返回行号，或目标可能被长 docstring/装饰器大幅前移导致窗口截断——应直接读更大范围
- 安全/门禁类全文件审计任务，窗口读会漏上下文，必须整文件读
