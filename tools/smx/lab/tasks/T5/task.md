# 任务 T5：按规格构建并验证产物

工作目录 `src/entries.txt` 有 10 行数据（每行形如 `key-NN,value=M`）。要求：

1. 编写脚本 `gen.py`（Python3，标准库）：读取 `src/entries.txt`，生成 `build/data.json`，结构为
   `{"items": [{"key": "<每行的 key 部分>", "value": <每行 value 的整数部分>}, ...], "count": <行数>}`；
   `build/` 不存在时自动创建；脚本可重复运行（重跑产物一致）；
2. 运行 `gen.py` 生成产物；
3. 把 `data.json` 中 `items` 的条目数写入 `build/count.txt`（一个整数，单独一行）。

完成判据（客观判定）：判定时重新运行 `python3 gen.py` 退出码 0；`build/data.json` 与 `src/entries.txt` 内容一一对应且 `count` 正确；`build/count.txt` 为正确条目数；`src/entries.txt` 与初始版本逐字节一致。
