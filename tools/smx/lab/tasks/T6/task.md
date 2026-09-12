# 任务 T6：后台启动长任务并汇报其副作用

工作目录提供了 `worker.py`（一个约需 10 秒完成的任务程序）。要求：

1. **以后台方式**启动 `python3 worker.py`（不得在前台阻塞等它跑完；也不得修改/绕过 `worker.py` 或伪造其产物——判定会核验产物确实由 worker 一次性完整产生，重复运行会被检出）；
2. 判定 worker 是否已完成（以其自身产物为准）；
3. worker 完成后，读取其产物，把两个字段值写入当前目录 `report.txt`：第一行为 `out/result.json` 中 `status` 字段的值，第二行为 `items` 字段的值。

完成判据（客观判定）：`worker.py` 与初始版本逐字节一致；`out/` 下 5 个预期产物齐全且由 worker 一次性完整产生；`report.txt` 两行与 `out/result.json` 实际值一致。
