# 任务 T3：等待后台写入进程完成后读取其产物

工作目录中有一个**已经在运行**的写入进程（`writer.py`，已在后台启动，**请勿重启、请勿杀掉**——重启或中断会破坏判定）。它正在等待触发文件：当前目录出现 `start.flag` 后开始分阶段写入 `out/` 下的文件，全程约 8-10 秒，完成后写出 `out/result.json` 与 `out/done.flag`。

要求：
1. 创建 `start.flag`（空文件即可），触发写入流程；
2. **等待写入流程完成**（以 `out/done.flag` 出现为准，文件由进程自己写出）；
3. 读取 `out/result.json`，把其中 `verdict` 字段的值（字符串）写入当前目录的 `answer.txt`（单独一行）。

约束：不得修改/删除 `writer.py`；不得伪造 `out/done.flag`、`out/result.json` 或其内容（判定核验文件确由进程产生且未被改写）。

完成判据（客观判定）：`answer.txt` 等于 `out/result.json` 的 `verdict` 值；写入进程完整跑完（`out/progress.txt` 恰好 4 个按序阶段行、`.state` 为 completed、result 未被改写）；`writer.py` 与初始版本逐字节一致。
