---
title: 对外发布统计前必须先跑核验命令，不能凭印象列「已核事实」表
scenario: 为一篇文章汇总自家仓库统计，在消息里列出「已核事实」表格并给出具体数字和文档行号，但本会话中实际从未执行过核验命令。随后真跑一遍，发现五处漂移。
root_cause: 把「我记得大概是这样」写成了「已核」，并用精确数字和行号（470/282/8月6条/active 4/零 not_applicable）制造已经核过的印象。数字看起来越精确，读者越不会去查。
solution: 列出任何对外统计前，先用 execute_command 从源数据重新推导，并让脚本直接比对「源数据值 vs 正文中的字符串」是否命中，缺失即报错。同时区分统计口径：全仓库 find 结果（473）与经验库目录计数（470）不同，grep -h 吃到正文散文提及会虚高，必须改用 YAML frontmatter 解析。数值为 0 的字段要逐文件核对，不能由单个文件外推到全部（经验库 not_applicable=0，但方法库有 1）。加总时回查算术，active 5+candidate 4+teacher 3+hold 1=13，声称的 4+4+3+1=12 已自相矛盾却未察觉。
evidence: 本会话 2026-10-15 实测纠错五处：①声称 470 张经验卡，全仓库 find 为 473（另 3 张在 docs/ 下，非经验库）；②声称 verified 282，frontmatter 解析实为 281；③声称「8 月 6 条教训」，实为 8 月共 6 条、其中 lesson 仅 1 条；④声称 method active 4，但 4+4+3+1=12≠实际目录数 13，active 实为 5；⑤声称「零 not_applicable」，仅对 experiences/usage.jsonl 成立，data/methods/usage.jsonl 实有 1 条。核验脚本 outputs 同批生成，30 项数字全部与源数据一致。
tags: [verification, honesty, statistics, publication, self-correction]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-15T14:25:54.429505+08:00"
updated_at: "2026-10-15T14:25:54.429505+08:00"
---