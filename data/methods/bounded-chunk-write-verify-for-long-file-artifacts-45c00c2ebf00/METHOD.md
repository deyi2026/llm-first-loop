---
method_id: bounded-chunk-write-verify-for-long-file-artifacts-45c00c2ebf00
name: bounded-chunk-write-verify-for-long-file-artifacts
description: 通过 shell heredoc/cat 写入长文档时，传输可能静默截断内容，而命令仍返回 exit 0——回执证明的是'执行了'，不是'写完整了'。对长度超过单次命令可靠规模的交付物，应预先切成有界块（首块 cat >，后续 cat >>），每块后核对回执中的累计行数，末块附文末哨兵；一旦回读发现行数不足或句中截断，不要追加修补，而是删除后按更小块重建。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6f6aaff7-affa-4ddd-ba99-dd5932331bbc:102:e26fcd9e93c11cc2710c
evidence_refs: learning:learn:f61039b450c9
created_at: 2026-09-29T14:14:10.640216+08:00
updated_at: 2026-09-29T14:14:10.640216+08:00
---
## Trigger
需要用 shell heredoc/cat 把长文档（数十行以上）写入文件交付物，或对一次写盘后的内容完整性没有独立回执、只能靠 exit 0 判断的场景。

## Discriminator
写入后立即可观察的事实：回执仅 exit 0 无输出，但 read_file 显示文件只有 8 行且在句中截断（预期约 115 行）——证明退出码与'成功'字样不等于内容完整；后续每个 ~30-45 行的 chunk 写入均完整到达预期行数（33→73→115、44→64→95），说明有界分块+逐块行数核对+文末哨兵可稳定绕开该失效模式。

## Short path
- 起草时按目标长度预切有界块，每块规模远小于出现截断的单次写入（本环境中 ~30-45 行的块均成功，单次 ~115 行写入在第 8 行被截断）
- 首块 cat > 写入，回执累计行数应等于该块预期行数
- 后续逐块 cat >> 追加，每块后核对累计行数（如 33→73→115）
- 末块确认最后一句完整并追加文末哨兵（如 NO_CORRUPTION_MARKER）
- read_file 抽查头/尾与句界完整性，再声明交付

## Stop conditions
- 累计行数与逐块预期一致，且文末哨兵在位/最后一句无句中截断，即可停止写入进入交付
- 某块后行数不符或尾部截断时，停止追加，删除重建为更小的块，不继续在同一文件上修补

## Verification
- 每个 chunk 后以回执中的累计行数核对预期值
- 最终 read_file 至少覆盖文件头、尾与截断敏感位置，确认无句中截断、哨兵在位
- 不以 shell exit 0 或'执行成功'作为长文档内容完整的证据

## Counterexamples
- 短文件（几行、远低于单次写入可靠规模）：单次写入+一次回读即可，分块只增加噪音与调用数
- 写入由专用 write_file 工具完成且回执自带字节数/行数：以该回执为准，无需 shell 分块
- 文件会被并发读者立即读取、不能容忍中间态：分块追加会暴露部分写入状态，应写临时文件后原子 rename，而非套用本方法
- 截断根因不是传输规模（如磁盘满、权限错误，通常表现为非零退出码或显式错误）：分块写不解决该类失败
