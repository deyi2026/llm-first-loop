# 任务 T4：批量重命名并验证

工作目录的 `files/` 子目录下有 40 个形如 `old_NN.txt`（NN=01..40）的文本文件。

要求：
1. 把每个 `old_NN.txt` 重命名为 `new_NN.txt`（编号保持不变，如 old_07.txt → new_07.txt），文件内容不得改变；
2. 验证重命名结果：40 个 `new_NN.txt` 齐全、`old_*.txt` 一个不剩；
3. 把验证结果写入当前目录 `summary.txt`，格式**恰好**一行：`renamed=40 remaining_old=0`（按你实际数出的值如实填写，判定时会与实际状态核对）。

完成判据（客观判定）：`files/` 下 `new_*.txt` 恰 40 个且编号齐全；`old_*.txt` 为 0；内容逐一未变（拼接校验和一致）；`summary.txt` 与实际值一致。
